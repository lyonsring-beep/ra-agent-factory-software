from __future__ import annotations

from contextlib import contextmanager
from datetime import UTC, datetime
from hashlib import sha256
import json
from pathlib import Path
import sqlite3
from threading import RLock
from typing import Iterator


class SQLiteStateStore:
    """Durable Studio projection + authority-support store.

    Immutable candidate bytes are content-addressed. Authority writes use BEGIN IMMEDIATE,
    versioned currentness pointers, fencing tokens, recovery epochs and a tamper-evident
    audit chain. Generic mutable records remain suitable for Studio projections only.
    """

    def __init__(self, path: str) -> None:
        self.path = path
        if path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
        self._conn.row_factory = sqlite3.Row
        self._lock = RLock()
        self._initialize()

    def _initialize(self) -> None:
        with self._lock:
            self._conn.executescript(
                """
                PRAGMA journal_mode=WAL;
                PRAGMA foreign_keys=ON;
                CREATE TABLE IF NOT EXISTS records (
                    kind TEXT NOT NULL,
                    record_key TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY(kind, record_key)
                );
                CREATE TABLE IF NOT EXISTS immutable_records (
                    kind TEXT NOT NULL,
                    record_key TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    payload_sha256 TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY(kind, record_key)
                );
                CREATE TABLE IF NOT EXISTS blobs (
                    sha256 TEXT PRIMARY KEY,
                    size_bytes INTEGER NOT NULL,
                    data BLOB NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS current_pointers (
                    pointer_kind TEXT NOT NULL,
                    pointer_key TEXT NOT NULL,
                    value TEXT NOT NULL,
                    version INTEGER NOT NULL,
                    recovery_epoch INTEGER NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY(pointer_kind, pointer_key)
                );
                CREATE TABLE IF NOT EXISTS promotion_locks (
                    lineage_id TEXT PRIMARY KEY,
                    fencing_token INTEGER NOT NULL,
                    holder TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS idempotency_records (
                    command_id TEXT PRIMARY KEY,
                    request_sha256 TEXT NOT NULL,
                    result_kind TEXT NOT NULL,
                    result_key TEXT NOT NULL,
                    recovery_epoch INTEGER NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS recovery_state (
                    singleton INTEGER PRIMARY KEY CHECK(singleton=1),
                    recovery_epoch INTEGER NOT NULL
                );
                INSERT OR IGNORE INTO recovery_state(singleton,recovery_epoch) VALUES(1,1);
                CREATE TABLE IF NOT EXISTS audit_events (
                    event_id TEXT PRIMARY KEY,
                    occurred_at TEXT NOT NULL,
                    actor_principal_id TEXT NOT NULL,
                    action TEXT NOT NULL,
                    subject_kind TEXT NOT NULL,
                    subject_id TEXT NOT NULL,
                    metadata TEXT NOT NULL,
                    prior_event_hash TEXT NOT NULL DEFAULT '',
                    event_hash TEXT NOT NULL DEFAULT ''
                );
                """
            )
            cols={row["name"] for row in self._conn.execute("PRAGMA table_info(audit_events)").fetchall()}
            if "prior_event_hash" not in cols:
                self._conn.execute("ALTER TABLE audit_events ADD COLUMN prior_event_hash TEXT NOT NULL DEFAULT ''")
            if "event_hash" not in cols:
                self._conn.execute("ALTER TABLE audit_events ADD COLUMN event_hash TEXT NOT NULL DEFAULT ''")

    @contextmanager
    def transaction(self) -> Iterator["SQLiteStateStore"]:
        with self._lock:
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                yield self
            except BaseException:
                self._conn.execute("ROLLBACK")
                raise
            else:
                self._conn.execute("COMMIT")

    @staticmethod
    def _encode(payload: dict) -> str:
        return json.dumps(payload, sort_keys=True, separators=(",", ":"))

    def put(self, kind: str, key: str, payload: dict) -> None:
        encoded=self._encode(payload)
        self._conn.execute(
            """INSERT INTO records(kind,record_key,payload,updated_at) VALUES(?,?,?,?)
               ON CONFLICT(kind,record_key) DO UPDATE SET payload=excluded.payload,updated_at=excluded.updated_at""",
            (kind,key,encoded,datetime.now(UTC).isoformat()),
        )

    def add(self, kind: str, key: str, payload: dict) -> None:
        encoded=self._encode(payload)
        try:
            self._conn.execute(
                "INSERT INTO records(kind,record_key,payload,updated_at) VALUES(?,?,?,?)",
                (kind,key,encoded,datetime.now(UTC).isoformat()),
            )
        except sqlite3.IntegrityError as exc:
            raise ValueError(f"record already exists: {kind}/{key}") from exc

    def add_immutable(self, kind: str, key: str, payload: dict) -> str:
        encoded=self._encode(payload)
        digest=sha256(encoded.encode()).hexdigest()
        try:
            self._conn.execute(
                "INSERT INTO immutable_records(kind,record_key,payload,payload_sha256,created_at) VALUES(?,?,?,?,?)",
                (kind,key,encoded,digest,datetime.now(UTC).isoformat()),
            )
        except sqlite3.IntegrityError:
            row=self._conn.execute(
                "SELECT payload_sha256 FROM immutable_records WHERE kind=? AND record_key=?",(kind,key)
            ).fetchone()
            if row is None or row["payload_sha256"] != digest:
                raise ValueError(f"immutable record mutation rejected: {kind}/{key}")
        return digest

    def get_immutable(self, kind: str, key: str) -> dict:
        row=self._conn.execute(
            "SELECT payload,payload_sha256 FROM immutable_records WHERE kind=? AND record_key=?",(kind,key)
        ).fetchone()
        if row is None:
            raise KeyError(f"unknown immutable record: {kind}/{key}")
        if sha256(row["payload"].encode()).hexdigest() != row["payload_sha256"]:
            raise RuntimeError(f"immutable record integrity failure: {kind}/{key}")
        return json.loads(row["payload"])

    def publish_blob(self, data: bytes) -> str:
        digest=sha256(data).hexdigest()
        self._conn.execute(
            "INSERT OR IGNORE INTO blobs(sha256,size_bytes,data,created_at) VALUES(?,?,?,?)",
            (digest,len(data),data,datetime.now(UTC).isoformat()),
        )
        row=self._conn.execute("SELECT size_bytes,data FROM blobs WHERE sha256=?",(digest,)).fetchone()
        if row is None or row["size_bytes"] != len(data) or bytes(row["data"]) != data:
            raise RuntimeError("content-addressed blob publication integrity failure")
        return digest

    def get_blob(self, digest: str) -> bytes:
        row=self._conn.execute("SELECT data FROM blobs WHERE sha256=?",(digest,)).fetchone()
        if row is None:
            raise KeyError(f"unknown blob: {digest}")
        data=bytes(row["data"])
        if sha256(data).hexdigest() != digest:
            raise RuntimeError("content-addressed blob integrity failure")
        return data

    def get(self, kind: str, key: str) -> dict:
        row=self._conn.execute("SELECT payload FROM records WHERE kind=? AND record_key=?",(kind,key)).fetchone()
        if row is None:
            raise KeyError(f"unknown record: {kind}/{key}")
        return json.loads(row["payload"])

    def get_optional(self, kind: str, key: str) -> dict | None:
        row=self._conn.execute("SELECT payload FROM records WHERE kind=? AND record_key=?",(kind,key)).fetchone()
        return json.loads(row["payload"]) if row is not None else None

    def list(self, kind: str) -> tuple[dict,...]:
        rows=self._conn.execute("SELECT payload FROM records WHERE kind=? ORDER BY record_key",(kind,)).fetchall()
        return tuple(json.loads(row["payload"]) for row in rows)

    def recovery_epoch(self) -> int:
        return int(self._conn.execute("SELECT recovery_epoch FROM recovery_state WHERE singleton=1").fetchone()[0])

    def bump_recovery_epoch(self) -> int:
        self._conn.execute("UPDATE recovery_state SET recovery_epoch=recovery_epoch+1 WHERE singleton=1")
        return self.recovery_epoch()

    def acquire_fencing_token(self, lineage_id: str, holder: str) -> int:
        row=self._conn.execute("SELECT fencing_token FROM promotion_locks WHERE lineage_id=?",(lineage_id,)).fetchone()
        token=(int(row["fencing_token"])+1) if row else 1
        self._conn.execute(
            """INSERT INTO promotion_locks(lineage_id,fencing_token,holder,updated_at) VALUES(?,?,?,?)
               ON CONFLICT(lineage_id) DO UPDATE SET fencing_token=excluded.fencing_token,holder=excluded.holder,updated_at=excluded.updated_at""",
            (lineage_id,token,holder,datetime.now(UTC).isoformat()),
        )
        return token

    def get_pointer(self, kind: str, key: str) -> dict | None:
        row=self._conn.execute(
            "SELECT value,version,recovery_epoch FROM current_pointers WHERE pointer_kind=? AND pointer_key=?",(kind,key)
        ).fetchone()
        return dict(row) if row else None

    def compare_and_set_pointer(
        self, kind: str, key: str, *, expected_value: str | None, new_value: str,
        expected_version: int | None, fencing_token: int | None = None,
    ) -> int:
        row=self.get_pointer(kind,key)
        actual_value=row["value"] if row else None
        actual_version=int(row["version"]) if row else 0
        if actual_value != expected_value:
            raise PermissionError("currentness pointer value changed")
        if expected_version is not None and actual_version != expected_version:
            raise PermissionError("ExpectedConsistencyVersion mismatch")
        if fencing_token is not None:
            lock=self._conn.execute("SELECT fencing_token FROM promotion_locks WHERE lineage_id=?",(key,)).fetchone()
            if lock is None or int(lock["fencing_token"]) != fencing_token:
                raise PermissionError("stale fencing token")
        new_version=actual_version+1
        self._conn.execute(
            """INSERT INTO current_pointers(pointer_kind,pointer_key,value,version,recovery_epoch,updated_at)
               VALUES(?,?,?,?,?,?)
               ON CONFLICT(pointer_kind,pointer_key) DO UPDATE SET
               value=excluded.value,version=excluded.version,recovery_epoch=excluded.recovery_epoch,updated_at=excluded.updated_at""",
            (kind,key,new_value,new_version,self.recovery_epoch(),datetime.now(UTC).isoformat()),
        )
        return new_version

    def record_idempotency(self, command_id: str, request_payload: dict, result_kind: str, result_key: str) -> None:
        digest=sha256(self._encode(request_payload).encode()).hexdigest()
        row=self._conn.execute("SELECT request_sha256,result_kind,result_key,recovery_epoch FROM idempotency_records WHERE command_id=?",(command_id,)).fetchone()
        if row is not None:
            if row["request_sha256"] != digest or row["result_kind"] != result_kind or row["result_key"] != result_key:
                raise PermissionError("duplicate command id with different request/result")
            if int(row["recovery_epoch"]) != self.recovery_epoch():
                raise PermissionError("stale recovery epoch idempotency record")
            return
        self._conn.execute(
            "INSERT INTO idempotency_records(command_id,request_sha256,result_kind,result_key,recovery_epoch,created_at) VALUES(?,?,?,?,?,?)",
            (command_id,digest,result_kind,result_key,self.recovery_epoch(),datetime.now(UTC).isoformat()),
        )

    def append_audit(self, *, event_id: str, actor_principal_id: str, action: str,
                     subject_kind: str, subject_id: str, metadata: dict, occurred_at: datetime) -> None:
        prior=self._conn.execute("SELECT event_hash FROM audit_events ORDER BY rowid DESC LIMIT 1").fetchone()
        prior_hash=(prior["event_hash"] if prior else "") or ""
        encoded_metadata=self._encode(metadata)
        canonical=self._encode({
            "event_id":event_id,"occurred_at":occurred_at.isoformat(),"actor":actor_principal_id,
            "action":action,"subject_kind":subject_kind,"subject_id":subject_id,
            "metadata":json.loads(encoded_metadata),"prior_event_hash":prior_hash,
        })
        event_hash=sha256(canonical.encode()).hexdigest()
        self._conn.execute(
            """INSERT INTO audit_events(event_id,occurred_at,actor_principal_id,action,subject_kind,subject_id,metadata,prior_event_hash,event_hash)
               VALUES(?,?,?,?,?,?,?,?,?)""",
            (event_id,occurred_at.isoformat(),actor_principal_id,action,subject_kind,subject_id,encoded_metadata,prior_hash,event_hash),
        )

    def list_audit(self) -> tuple[dict,...]:
        rows=self._conn.execute("SELECT * FROM audit_events ORDER BY rowid").fetchall()
        out=[]
        prior=""
        for row in rows:
            canonical=self._encode({
                "event_id":row["event_id"],"occurred_at":row["occurred_at"],"actor":row["actor_principal_id"],
                "action":row["action"],"subject_kind":row["subject_kind"],"subject_id":row["subject_id"],
                "metadata":json.loads(row["metadata"]),"prior_event_hash":row["prior_event_hash"],
            })
            expected=sha256(canonical.encode()).hexdigest()
            if row["prior_event_hash"] != prior or row["event_hash"] != expected:
                raise RuntimeError("audit integrity standing failed")
            prior=row["event_hash"]
            out.append({
                "event_id":row["event_id"],"occurred_at":row["occurred_at"],
                "actor_principal_id":row["actor_principal_id"],"action":row["action"],
                "subject_kind":row["subject_kind"],"subject_id":row["subject_id"],
                "metadata":json.loads(row["metadata"]),"prior_event_hash":row["prior_event_hash"],
                "event_hash":row["event_hash"],
            })
        return tuple(out)

    def close(self) -> None:
        with self._lock:
            self._conn.close()

from __future__ import annotations

from contextlib import contextmanager
from datetime import UTC, datetime
import json
from pathlib import Path
import sqlite3
from threading import RLock
from typing import Iterator


class SQLiteStateStore:
    """Durable authoritative record store with explicit write transactions.

    Domain objects are stored as canonical JSON records. Authority transitions use
    BEGIN IMMEDIATE so baseline/currentness checks and writes happen in one critical section.
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
                CREATE TABLE IF NOT EXISTS audit_events (
                    event_id TEXT PRIMARY KEY,
                    occurred_at TEXT NOT NULL,
                    actor_principal_id TEXT NOT NULL,
                    action TEXT NOT NULL,
                    subject_kind TEXT NOT NULL,
                    subject_id TEXT NOT NULL,
                    metadata TEXT NOT NULL
                );
                """
            )

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

    def put(self, kind: str, key: str, payload: dict) -> None:
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        self._conn.execute(
            """
            INSERT INTO records(kind, record_key, payload, updated_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(kind, record_key) DO UPDATE SET
                payload=excluded.payload,
                updated_at=excluded.updated_at
            """,
            (kind, key, encoded, datetime.now(UTC).isoformat()),
        )

    def add(self, kind: str, key: str, payload: dict) -> None:
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        try:
            self._conn.execute(
                "INSERT INTO records(kind, record_key, payload, updated_at) VALUES (?, ?, ?, ?)",
                (kind, key, encoded, datetime.now(UTC).isoformat()),
            )
        except sqlite3.IntegrityError as exc:
            raise ValueError(f"record already exists: {kind}/{key}") from exc

    def get(self, kind: str, key: str) -> dict:
        row = self._conn.execute(
            "SELECT payload FROM records WHERE kind=? AND record_key=?", (kind, key)
        ).fetchone()
        if row is None:
            raise KeyError(f"unknown record: {kind}/{key}")
        return json.loads(row["payload"])

    def get_optional(self, kind: str, key: str) -> dict | None:
        row = self._conn.execute(
            "SELECT payload FROM records WHERE kind=? AND record_key=?", (kind, key)
        ).fetchone()
        return json.loads(row["payload"]) if row is not None else None

    def list(self, kind: str) -> tuple[dict, ...]:
        rows = self._conn.execute(
            "SELECT payload FROM records WHERE kind=? ORDER BY record_key", (kind,)
        ).fetchall()
        return tuple(json.loads(row["payload"]) for row in rows)

    def append_audit(
        self,
        *,
        event_id: str,
        actor_principal_id: str,
        action: str,
        subject_kind: str,
        subject_id: str,
        metadata: dict,
        occurred_at: datetime,
    ) -> None:
        self._conn.execute(
            """
            INSERT INTO audit_events(event_id, occurred_at, actor_principal_id, action, subject_kind, subject_id, metadata)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event_id,
                occurred_at.isoformat(),
                actor_principal_id,
                action,
                subject_kind,
                subject_id,
                json.dumps(metadata, sort_keys=True, separators=(",", ":")),
            ),
        )

    def list_audit(self) -> tuple[dict, ...]:
        rows = self._conn.execute(
            "SELECT * FROM audit_events ORDER BY occurred_at, event_id"
        ).fetchall()
        return tuple(
            {
                "event_id": row["event_id"],
                "occurred_at": row["occurred_at"],
                "actor_principal_id": row["actor_principal_id"],
                "action": row["action"],
                "subject_kind": row["subject_kind"],
                "subject_id": row["subject_id"],
                "metadata": json.loads(row["metadata"]),
            }
            for row in rows
        )

    def close(self) -> None:
        with self._lock:
            self._conn.close()

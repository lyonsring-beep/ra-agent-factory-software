from __future__ import annotations

import base64
from dataclasses import dataclass
import json
import os
from pathlib import Path
import shlex
import sqlite3
import subprocess
import tempfile
from typing import Protocol

from ra_agent_studio.domain.composition import RealizedAgentComposition
from ra_agent_studio.domain.identity import ContentHash


FACTORY_V111_COMMIT = "bc0568926ef70ea6fa7e5e6cc8287c09e041fb4f"
FACTORY_V111_CANDIDATE_SHA256 = "8387b7aa27d39be56a4f1e28ae979f9f233b1f29c196b5339c1b40dd6fdfec7b"
FACTORY_V111_CANDIDATE_SIZE = 1089023
FACTORY_V111_RUNTIME_IDENTITY = "ra-agent-factory-v1.11-frozen"


@dataclass(frozen=True, slots=True)
class FactoryBuildResult:
    artifact_hash: ContentHash
    factory_evidence_hash: ContentHash
    runtime_commit: str
    factory_candidate_sha256: str
    reproducible: bool
    artifact_path: str
    evidence_path: str

    def __post_init__(self) -> None:
        if self.runtime_commit != FACTORY_V111_COMMIT:
            raise RuntimeError("Factory runtime commit does not match frozen v1.11 identity")
        if self.factory_candidate_sha256 != FACTORY_V111_CANDIDATE_SHA256:
            raise RuntimeError("Factory candidate hash does not match frozen v1.11 identity")
        if not self.reproducible:
            raise RuntimeError("Factory result lacks reproducibility proof")


class FactoryRuntime(Protocol):
    def realize(self, composition: RealizedAgentComposition) -> FactoryBuildResult: ...


class SubprocessFactoryRuntime:
    """Adapter for the exact frozen RA Agent Factory v1.11 runtime.

    The bridge command receives request JSON and response JSON paths. Studio resolves the
    exact authoritative module bytes from its persistent state store, sends them to Factory,
    independently checks the exact frozen Factory identity and hashes the artifact/evidence
    bytes returned by Factory. There is no production simulation fallback.
    """

    def __init__(self, command: str, *, studio_db_path: str | None = None) -> None:
        if not command.strip():
            raise ValueError("Factory v1.11 command must be configured")
        self.command = command
        self.studio_db_path = studio_db_path or os.environ.get("RA_STUDIO_DB_PATH", "ra_agent_studio.db")

    @classmethod
    def from_environment(cls) -> "SubprocessFactoryRuntime":
        command = os.environ.get("RA_FACTORY_V111_COMMAND", "")
        if not command:
            raise RuntimeError(
                "RA_FACTORY_V111_COMMAND is required; Studio will not simulate Factory v1.11 builds"
            )
        return cls(command)

    def _load_exact_module_payload(self, revision_id: str) -> dict:
        conn = sqlite3.connect(self.studio_db_path)
        try:
            row = conn.execute(
                "SELECT payload FROM records WHERE kind='module' AND record_key=?",
                (revision_id,),
            ).fetchone()
        finally:
            conn.close()
        if row is None:
            raise RuntimeError(f"authoritative module revision not found: {revision_id}")
        return json.loads(row[0])

    def realize(self, composition: RealizedAgentComposition) -> FactoryBuildResult:
        request_bindings = []
        for binding in composition.bindings:
            module = self._load_exact_module_payload(binding.revision_id.value)
            if module["content_hash"] != binding.content_hash.value:
                raise RuntimeError(f"module payload hash drift for {binding.revision_id.value}")
            if module.get("config_hash") != (binding.config_hash.value if binding.config_hash else None):
                raise RuntimeError(f"module config hash drift for {binding.revision_id.value}")
            request_bindings.append(
                {
                    "module_id": binding.module_id.value,
                    "studio_revision_id": binding.revision_id.value,
                    "studio_content_hash": binding.content_hash.value,
                    "config_hash": binding.config_hash.value if binding.config_hash else None,
                    "content_base64": base64.b64encode(module["content"].encode("utf-8")).decode("ascii"),
                    "provided_capabilities": list(binding.provided_capabilities),
                    "required_capabilities": list(binding.required_capabilities),
                }
            )
        request = {
            "contract": "ra-agent-studio/factory-v1.11-realize/v2",
            "expected_factory_commit": FACTORY_V111_COMMIT,
            "expected_factory_candidate_sha256": FACTORY_V111_CANDIDATE_SHA256,
            "expected_factory_candidate_size": FACTORY_V111_CANDIDATE_SIZE,
            "studio_composition_id": composition.composition_id,
            "studio_composition_hash": composition.composition_hash.value,
            "bindings": request_bindings,
        }
        with tempfile.TemporaryDirectory(prefix="ra-studio-factory-") as temp_dir:
            temp = Path(temp_dir)
            request_path = temp / "request.json"
            response_path = temp / "response.json"
            request_path.write_text(json.dumps(request, sort_keys=True), encoding="utf-8")
            completed = subprocess.run(
                [*shlex.split(self.command), str(request_path), str(response_path)],
                text=True,
                capture_output=True,
                check=False,
            )
            if completed.returncode != 0:
                raise RuntimeError(
                    f"Factory v1.11 realization failed ({completed.returncode}): {completed.stderr.strip()}"
                )
            if not response_path.exists():
                raise RuntimeError("Factory v1.11 did not produce the required response manifest")
            response = json.loads(response_path.read_text(encoding="utf-8"))
            runtime_commit = response.get("factory_runtime_commit")
            factory_candidate_sha256 = response.get("factory_candidate_sha256")
            if runtime_commit != FACTORY_V111_COMMIT:
                raise RuntimeError("Factory runtime commit does not match frozen v1.11 identity")
            if factory_candidate_sha256 != FACTORY_V111_CANDIDATE_SHA256:
                raise RuntimeError("Factory candidate hash does not match frozen v1.11 identity")
            artifact_path = Path(response["artifact_path"])
            evidence_path = Path(response["evidence_path"])
            if not artifact_path.is_file() or not evidence_path.is_file():
                raise RuntimeError("Factory response references missing artifact/evidence files")
            artifact_hash = ContentHash.from_bytes(artifact_path.read_bytes())
            evidence_hash = ContentHash.from_bytes(evidence_path.read_bytes())
            if response.get("artifact_sha256") != artifact_hash.value:
                raise RuntimeError("Factory response artifact hash does not match produced bytes")
            rebuild_hash = response.get("rebuild_artifact_sha256")
            reproducible = bool(response.get("reproducible")) and rebuild_hash == artifact_hash.value
            if not reproducible:
                raise RuntimeError("Factory build did not supply reproducibility proof for exact artifact bytes")
            return FactoryBuildResult(
                artifact_hash=artifact_hash,
                factory_evidence_hash=evidence_hash,
                runtime_commit=runtime_commit,
                factory_candidate_sha256=factory_candidate_sha256,
                reproducible=True,
                artifact_path=str(artifact_path),
                evidence_path=str(evidence_path),
            )

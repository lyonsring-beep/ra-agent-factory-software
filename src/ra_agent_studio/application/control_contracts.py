from __future__ import annotations

from dataclasses import dataclass, field
from hashlib import sha256
import json
from typing import Any, Mapping

from .operation_catalog import descriptor


@dataclass(frozen=True, slots=True)
class CommandEnvelope:
    command_id: str
    operation_descriptor_id: str
    exact_target_ref: str
    principal_ref: str
    workspace_ref: str
    idempotency_key: str
    expected_recovery_epoch: int
    payload: Mapping[str, Any] = field(default_factory=dict)
    expected_target_version: int | None = None

    @property
    def payload_identity(self) -> str:
        raw=json.dumps(dict(self.payload),sort_keys=True,separators=(",",":"),default=str).encode()
        return sha256(raw).hexdigest()

    def validate(self) -> None:
        d=descriptor(self.operation_descriptor_id)
        if not self.command_id or not self.exact_target_ref or not self.principal_ref:
            raise ValueError("COMMAND_ID_EXACT_TARGET_AND_PRINCIPAL_REQUIRED")
        if d.authority_changing:
            if not self.workspace_ref:
                raise ValueError("WORKSPACE_REQUIRED")
            if not self.idempotency_key:
                raise ValueError("IDEMPOTENCY_KEY_REQUIRED")
            if self.expected_recovery_epoch < 1:
                raise ValueError("EXPECTED_RECOVERY_EPOCH_REQUIRED")


@dataclass(frozen=True, slots=True)
class CommandResult:
    standing: str
    command_id: str
    result_ref: str | None = None
    payload: Mapping[str, Any] = field(default_factory=dict)
    rejection_reason: str | None = None

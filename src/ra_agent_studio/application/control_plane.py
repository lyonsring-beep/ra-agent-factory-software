from __future__ import annotations

from dataclasses import asdict
from hashlib import sha256
import json

from .control_contracts import CommandEnvelope, CommandResult
from .operation_catalog import APPLICATION_OPERATION_CATALOG
from .studio import StudioService


class StudioControlPlane:
    """Closed B12 command surface over authoritative Studio services.

    Descriptor membership is architecture-owned and closed. Unknown/dynamic descriptors are
    rejected. Authority-changing commands require exact target, authenticated principal,
    workspace, idempotency key and current RecoveryEpoch via CommandEnvelope.validate().
    """

    def __init__(self, studio: StudioService):
        self.studio=studio

    @staticmethod
    def _request_digest(command: CommandEnvelope) -> str:
        raw=json.dumps({
            "operation_descriptor_id":command.operation_descriptor_id,
            "exact_target_ref":command.exact_target_ref,
            "principal_ref":command.principal_ref,
            "workspace_ref":command.workspace_ref,
            "idempotency_key":command.idempotency_key,
            "expected_recovery_epoch":command.expected_recovery_epoch,
            "payload":dict(command.payload),
        },sort_keys=True,separators=(",",":"),default=str).encode()
        return sha256(raw).hexdigest()

    def execute(self, command: CommandEnvelope) -> CommandResult:
        try:
            command.validate()
        except (ValueError,PermissionError) as exc:
            return CommandResult("REJECTED",command.command_id,rejection_reason=str(exc))
        if command.operation_descriptor_id not in APPLICATION_OPERATION_CATALOG:
            return CommandResult("REJECTED",command.command_id,rejection_reason="UNKNOWN_OPERATION_DESCRIPTOR")
        if command.expected_recovery_epoch != self.studio.store.recovery_epoch():
            return CommandResult("REJECTED",command.command_id,rejection_reason="STALE_RECOVERY_EPOCH")

        prior=self.studio.store.get_idempotency(command.command_id)
        request_digest=self._request_digest(command)
        if prior is not None:
            if prior["request_sha256"] != request_digest:
                return CommandResult("REJECTED",command.command_id,rejection_reason="IDEMPOTENCY_REQUEST_MISMATCH")
            return CommandResult("REPLAYED",command.command_id,result_ref=prior["result_key"],payload={"result_kind":prior["result_kind"]})

        p=dict(command.payload)
        try:
            result=self._dispatch(command,p)
        except (ValueError,KeyError,PermissionError,RuntimeError) as exc:
            return CommandResult("REJECTED",command.command_id,rejection_reason=str(exc))
        if result.standing == "COMMITTED":
            with self.studio.store.transaction():
                # record_idempotency hashes exactly the authoritative envelope payload supplied here.
                canonical_request={
                    "operation_descriptor_id":command.operation_descriptor_id,
                    "exact_target_ref":command.exact_target_ref,
                    "principal_ref":command.principal_ref,
                    "workspace_ref":command.workspace_ref,
                    "idempotency_key":command.idempotency_key,
                    "expected_recovery_epoch":command.expected_recovery_epoch,
                    "payload":p,
                }
                # Store the same digest contract used above.
                encoded=json.dumps(canonical_request,sort_keys=True,separators=(",",":"),default=str).encode()
                digest=sha256(encoded).hexdigest()
                self.studio.store._conn.execute(
                    "INSERT INTO idempotency_records(command_id,request_sha256,result_kind,result_key,recovery_epoch,created_at) VALUES(?,?,?,?,?,datetime('now'))",
                    (command.command_id,digest,result.payload.get("result_kind","command_result"),result.result_ref or "",self.studio.store.recovery_epoch()),
                )
        return result

    def _dispatch(self, c: CommandEnvelope, p: dict) -> CommandResult:
        op=c.operation_descriptor_id
        principal=c.principal_ref
        if op == "op:factory:exact-freeze":
            rec=self.studio.freeze(
                candidate_id=c.exact_target_ref,review_id=str(p["review_id"]),actor_principal_id=principal,
            )
            return CommandResult("COMMITTED",c.command_id,rec.frozen_artifact.id.value,{"result_kind":"freeze"})
        if op == "op:factory:canonical-promote":
            rec=self.studio.create_baseline(
                baseline_id=str(p["baseline_id"]),lineage_id=str(p["lineage_id"]),
                frozen_artifact_id=c.exact_target_ref,
                expected_predecessor_baseline_id=p.get("expected_predecessor_baseline_id"),
                actor_principal_id=principal,
            )
            return CommandResult("COMMITTED",c.command_id,rec.baseline_id.value,{"result_kind":"baseline"})
        if op == "op:deployment:authorize-deployment":
            rec=self.studio.authorize_deployment(
                deployment_id=str(p["deployment_id"]),frozen_artifact_id=c.exact_target_ref,
                actor_principal_id=principal,runtime_profile=dict(p["runtime_profile"]),
                environment=dict(p["environment"]),provider_binding=dict(p["provider_binding"]),
                secret_scope=dict(p.get("secret_scope",{})),permission_scope=dict(p.get("permission_scope",{})),
                policy=dict(p["policy"]),runtime_boundary=dict(p["runtime_boundary"]),
            )
            return CommandResult("COMMITTED",c.command_id,rec.deployment_id,{"result_kind":"deployment_authorization"})
        if op == "op:deployment:activate-runtime":
            attempt=self.studio.begin_activation(deployment_id=c.exact_target_ref,actor_principal_id=principal)
            return CommandResult("COMMITTED",c.command_id,attempt,{"result_kind":"activation_attempt"})
        if op == "op:deployment:stop-runtime":
            rec=self.studio.stop_runtime(deployment_id=c.exact_target_ref,actor_principal_id=principal)
            return CommandResult("COMMITTED",c.command_id,rec.deployment_id,{"result_kind":"runtime_stop"})
        if op == "op:deployment:revoke-deployment-grant":
            rec=self.studio.revoke_deployment(
                deployment_id=c.exact_target_ref,actor_principal_id=principal,reason=str(p.get("reason","revoked")),
            )
            return CommandResult("COMMITTED",c.command_id,rec.deployment_id,{"result_kind":"deployment_revocation"})
        if op == "op:deployment:place-safety-hold":
            rec=self.studio.place_safety_hold(deployment_id=c.exact_target_ref,actor_principal_id=principal)
            return CommandResult("COMMITTED",c.command_id,rec.deployment_id,{"result_kind":"deployment_hold"})
        return CommandResult("REJECTED",c.command_id,rejection_reason="OPERATION_NOT_PROJECTED_BY_STUDIO")

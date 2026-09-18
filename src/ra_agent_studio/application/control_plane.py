from __future__ import annotations

from hashlib import sha256
import json

from ra_agent_studio.domain.effect import EffectFixture
from ra_agent_studio.domain.review import ReviewBlocker

from .control_contracts import CommandEnvelope, CommandResult
from .operation_catalog import APPLICATION_OPERATION_CATALOG
from .studio import StudioService


class StudioControlPlane:
    """The single public B12 authority-changing control plane.

    All public mutations enter as CommandEnvelope. The command mutation and its durable
    idempotency result are committed in one outer authoritative transaction; nested service
    transactions are SAVEPOINTs under that same commit.
    """

    def __init__(self, studio: StudioService):
        self.studio=studio

    @staticmethod
    def _request_payload(command: CommandEnvelope) -> dict:
        return {
            "operation_descriptor_id":command.operation_descriptor_id,
            "exact_target_ref":command.exact_target_ref,
            "principal_ref":command.principal_ref,
            "workspace_ref":command.workspace_ref,
            "idempotency_key":command.idempotency_key,
            "expected_recovery_epoch":command.expected_recovery_epoch,
            "payload":dict(command.payload),
        }

    @classmethod
    def _request_digest(cls, command: CommandEnvelope) -> str:
        raw=json.dumps(
            cls._request_payload(command),
            sort_keys=True,separators=(",",":"),default=str,
        ).encode()
        return sha256(raw).hexdigest()

    def execute(self, command: CommandEnvelope) -> CommandResult:
        try:
            command.validate()
        except (ValueError,PermissionError) as exc:
            return CommandResult("REJECTED",command.command_id,rejection_reason=str(exc))
        if command.operation_descriptor_id not in APPLICATION_OPERATION_CATALOG:
            return CommandResult("REJECTED",command.command_id,rejection_reason="UNKNOWN_OPERATION_DESCRIPTOR")

        request_digest=self._request_digest(command)
        result: CommandResult
        try:
            with self.studio.store.transaction():
                if command.expected_recovery_epoch != self.studio.store.recovery_epoch():
                    raise PermissionError("STALE_RECOVERY_EPOCH")
                prior=self.studio.store.get_idempotency(command.command_id)
                if prior is not None:
                    if prior["request_sha256"] != request_digest:
                        raise PermissionError("IDEMPOTENCY_REQUEST_MISMATCH")
                    result=CommandResult(
                        "REPLAYED",command.command_id,result_ref=prior["result_key"],
                        payload={"result_kind":prior["result_kind"]},
                    )
                else:
                    result=self._dispatch(command,dict(command.payload))
                    if result.standing == "COMMITTED":
                        self.studio.store._conn.execute(
                            """INSERT INTO idempotency_records(
                                command_id,request_sha256,result_kind,result_key,recovery_epoch,created_at
                            ) VALUES(?,?,?,?,?,datetime('now'))""",
                            (
                                command.command_id,
                                request_digest,
                                result.payload.get("result_kind","command_result"),
                                result.result_ref or "",
                                self.studio.store.recovery_epoch(),
                            ),
                        )
                        self.studio.store.add_immutable("command_commit",command.command_id,{
                            "command_id":command.command_id,
                            "operation_descriptor_id":command.operation_descriptor_id,
                            "exact_target_ref":command.exact_target_ref,
                            "principal_ref":command.principal_ref,
                            "workspace_ref":command.workspace_ref,
                            "request_sha256":request_digest,
                            "result_kind":result.payload.get("result_kind","command_result"),
                            "result_ref":result.result_ref or "",
                            "recovery_epoch":self.studio.store.recovery_epoch(),
                            "atomic_with_authority_mutation":True,
                        })
        except (ValueError,KeyError,PermissionError,RuntimeError) as exc:
            return CommandResult("REJECTED",command.command_id,rejection_reason=str(exc))

        # External runtime side effects happen only after the durable command/attempt reservation
        # commits. Provider calls receive that durable attempt id as their idempotency key. A
        # process crash can therefore be resumed from the same attempt instead of synthesizing
        # ACTIVE/STOPPED or re-authorizing a new side effect.
        result_kind=str(result.payload.get("result_kind",""))
        if result.result_ref and result_kind == "activation_attempt":
            try:
                rec=self.studio.execute_activation_attempt(
                    activation_attempt_id=result.result_ref,
                    actor_principal_id=command.principal_ref,
                )
            except (ValueError,KeyError,PermissionError,RuntimeError) as exc:
                return CommandResult(
                    result.standing,command.command_id,result_ref=result.result_ref,
                    payload={"result_kind":result_kind,"runtime_standing":"ACTIVATING"},
                    rejection_reason=f"provider execution unresolved: {exc}",
                )
            return CommandResult(
                result.standing,command.command_id,result_ref=result.result_ref,
                payload={"result_kind":result_kind,"runtime_standing":rec.runtime_standing.value},
            )
        if result.result_ref and result_kind == "stop_attempt":
            try:
                rec=self.studio.execute_stop_attempt(
                    stop_attempt_id=result.result_ref,
                    actor_principal_id=command.principal_ref,
                )
            except (ValueError,KeyError,PermissionError,RuntimeError) as exc:
                return CommandResult(
                    result.standing,command.command_id,result_ref=result.result_ref,
                    payload={"result_kind":result_kind,"runtime_standing":"STOPPING"},
                    rejection_reason=f"provider stop unresolved: {exc}",
                )
            return CommandResult(
                result.standing,command.command_id,result_ref=result.result_ref,
                payload={"result_kind":result_kind,"runtime_standing":rec.runtime_standing.value},
            )
        return result

    def _dispatch(self, c: CommandEnvelope, p: dict) -> CommandResult:
        op=c.operation_descriptor_id
        principal=c.principal_ref

        if op == "op:factory:module-revision-create":
            revision=self.studio.create_module_revision(
                module_id=str(p["module_id"]),
                revision_id=c.exact_target_ref,
                name=str(p["name"]),
                content=str(p["content"]),
                actor_principal_id=principal,
                predecessor_revision_id=p.get("predecessor_revision_id"),
                provided_capabilities=tuple(p.get("provided_capabilities",[])),
                required_capabilities=tuple(p.get("required_capabilities",[])),
                required_module_ids=tuple(p.get("required_module_ids",[])),
                incompatible_module_ids=tuple(p.get("incompatible_module_ids",[])),
                identity_domain=str(p.get("identity_domain","")),
                config_json=str(p.get("config_json","{}")),
                module_type=str(p.get("module_type","AGENT_SPECIFIC_EXTENSION_MODULE")),
                authority_class=str(p.get("authority_class","FACTORY_AGENT_SPECIFIC")),
                editability=str(p.get("editability","agent_editable")),
                agent_requirement_ref=str(p.get("agent_requirement_ref","ra-agent-studio:default-requirement")),
                agent_authority_boundary_ref=str(p.get("agent_authority_boundary_ref","ra-agent-studio:default-authority-boundary")),
                shared_change_authorization_ref=str(p.get("shared_change_authorization_ref","")),
            )
            return CommandResult("COMMITTED",c.command_id,revision.revision_id.value,{"result_kind":"module_revision"})

        if op == "op:factory:composition-realize":
            composition=self.studio.compose(
                c.exact_target_ref,list(p["revision_ids"]),actor_principal_id=principal,
            )
            return CommandResult("COMMITTED",c.command_id,composition.composition_id,{"result_kind":"composition"})

        if op == "op:factory:candidate-build":
            evidence,candidate=self.studio.build(
                c.exact_target_ref,
                actor_principal_id=principal,
                workspace_id=c.workspace_ref,
                lineage_id=str(p["lineage_id"]),
                predecessor_baseline_id=p.get("predecessor_baseline_id"),
                upstream_handoff_ref=str(p.get(
                    "upstream_handoff_ref",
                    "RA_AGENT_STUDIO_FORMAL_SOFTWARE_DESIGN_FROZEN_HANDOFF",
                )),
            )
            return CommandResult(
                "COMMITTED",c.command_id,candidate.candidate_id.value,
                {"result_kind":"implementation_candidate","evidence_id":evidence.evidence_id},
            )

        if op == "op:factory:controlled-execution-run":
            fixture=EffectFixture(
                str(p["fixture_id"]),str(p.get("input_text","")),
                tuple(p.get("expected_contains",[])),
            )
            observation=self.studio.run_effect_fixture(c.exact_target_ref,fixture)
            return CommandResult(
                "COMMITTED",c.command_id,
                f"{c.exact_target_ref}:{fixture.fixture_identity}",
                {"result_kind":"controlled_execution_observation","passed":observation.passed},
            )

        if op == "op:factory:review-decision-ingest":
            blockers=tuple(
                ReviewBlocker(
                    str(x["blocker_id"]),str(x["description"]),bool(x.get("closed",False))
                )
                for x in p.get("blockers",[])
            )
            review=self.studio.review(
                candidate_id=c.exact_target_ref,
                reviewer_principal_id=principal,
                review_method=str(p["review_method"]),
                passed=p.get("passed"),
                verdict=p.get("verdict"),
                blockers=blockers,
                failure_class=p.get("failure_class"),
                mutation_standing=str(p.get("mutation_standing","UNCHANGED")),
                authorized_reopen_scope=tuple(p.get("authorized_reopen_scope",[])),
            )
            return CommandResult("COMMITTED",c.command_id,review.review_id,{"result_kind":"review"})

        if op == "op:factory:exact-freeze":
            rec=self.studio.freeze(
                candidate_id=c.exact_target_ref,
                review_id=str(p["review_id"]),
                actor_principal_id=principal,
            )
            return CommandResult("COMMITTED",c.command_id,rec.frozen_artifact.id.value,{"result_kind":"freeze"})

        if op == "op:factory:canonical-promote":
            rec=self.studio.create_baseline(
                baseline_id=str(p["baseline_id"]),
                lineage_id=str(p["lineage_id"]),
                frozen_artifact_id=c.exact_target_ref,
                expected_predecessor_baseline_id=p.get("expected_predecessor_baseline_id"),
                actor_principal_id=principal,
            )
            return CommandResult("COMMITTED",c.command_id,rec.baseline_id.value,{"result_kind":"baseline"})

        if op == "op:deployment:authorize-deployment":
            rec=self.studio.authorize_deployment(
                deployment_id=str(p["deployment_id"]),
                frozen_artifact_id=c.exact_target_ref,
                actor_principal_id=principal,
                runtime_profile=dict(p["runtime_profile"]),
                environment=dict(p["environment"]),
                provider_binding=dict(p["provider_binding"]),
                secret_scope=dict(p.get("secret_scope",{})),
                permission_scope=dict(p.get("permission_scope",{})),
                policy=dict(p["policy"]),
                runtime_boundary=dict(p["runtime_boundary"]),
            )
            return CommandResult("COMMITTED",c.command_id,rec.deployment_id,{"result_kind":"deployment_authorization"})

        if op == "op:deployment:activate-runtime":
            attempt=self.studio.begin_activation(
                deployment_id=c.exact_target_ref,actor_principal_id=principal
            )
            return CommandResult(
                "COMMITTED",c.command_id,attempt,{"result_kind":"activation_attempt"},
            )

        if op == "op:deployment:stop-runtime":
            attempt=self.studio.begin_stop_runtime(
                deployment_id=c.exact_target_ref,actor_principal_id=principal
            )
            return CommandResult(
                "COMMITTED",c.command_id,attempt,{"result_kind":"stop_attempt"},
            )

        if op == "op:deployment:revoke-deployment-grant":
            rec=self.studio.revoke_deployment(
                deployment_id=c.exact_target_ref,
                actor_principal_id=principal,
                reason=str(p.get("reason","revoked")),
            )
            return CommandResult("COMMITTED",c.command_id,rec.deployment_id,{"result_kind":"deployment_revocation"})

        if op == "op:deployment:place-safety-hold":
            rec=self.studio.place_safety_hold(
                deployment_id=c.exact_target_ref,actor_principal_id=principal
            )
            return CommandResult("COMMITTED",c.command_id,rec.deployment_id,{"result_kind":"deployment_hold"})

        if op in {"op:deployment:remove-safety-hold","op:deployment:revalidate-deployment"}:
            rec=self.studio.revalidate_deployment(
                deployment_id=c.exact_target_ref,
                actor_principal_id=principal,
                continue_active=bool(p.get("continue_active",False)),
            )
            kind=(
                "deployment_hold_removed_revalidated"
                if op.endswith("remove-safety-hold")
                else "deployment_revalidation"
            )
            return CommandResult("COMMITTED",c.command_id,rec.deployment_id,{"result_kind":kind})

        return CommandResult("REJECTED",c.command_id,rejection_reason="OPERATION_NOT_PROJECTED_BY_STUDIO")

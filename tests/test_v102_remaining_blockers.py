from __future__ import annotations

from pathlib import Path

import pytest

from ra_agent_studio.application.control_contracts import CommandEnvelope
from ra_agent_studio.application.control_plane import StudioControlPlane
from ra_agent_studio.application.studio import StudioService
from ra_agent_studio.domain.failure_routing import CandidateMutationStanding, FailureClass
from ra_agent_studio.domain.module import ModuleAuthorityClass, ModuleEditability, ModuleType
from ra_agent_studio.domain.production import ProductionState
from ra_agent_studio.infra.sqlite import SQLiteStateStore
from tests.support import ContractTestFactoryRuntime, authority_registry


def service(tmp_path: Path) -> StudioService:
    return StudioService(
        db_path=str(tmp_path/"v102-extra.db"),
        authority_registry=authority_registry(),
        factory_runtime=ContractTestFactoryRuntime(),
    )


def build_candidate(s: StudioService, suffix: str="1"):
    s.create_module_revision(
        module_id=f"m{suffix}",revision_id=f"r{suffix}",name=f"M{suffix}",content="print('ok')",
        actor_principal_id="builder",provided_capabilities=("answer",),identity_domain=f"d{suffix}",
    )
    s.compose(f"c{suffix}",[f"r{suffix}"],actor_principal_id="builder")
    return s.build(f"c{suffix}",actor_principal_id="builder",workspace_id="ws",lineage_id=f"lineage-{suffix}")[1]


@pytest.mark.parametrize(
    "failure_class,mutation,expected",
    [
        (FailureClass.FC_1_DESIGN_DEFECT.value,CandidateMutationStanding.UNCHANGED.value,ProductionState.PR_12_DESIGN_REOPEN_REQUIRED.value),
        (FailureClass.FC_2_LOCAL_IMPLEMENTATION_DEFECT.value,CandidateMutationStanding.CANDIDATE_MUTATING.value,ProductionState.PR_11_IMPLEMENTATION_REPAIR_AUTHORIZED.value),
        (FailureClass.FC_3_SHARED_ARCHITECTURE_REQUIREMENT.value,CandidateMutationStanding.UNCHANGED.value,ProductionState.PR_13_SHARED_REVIEW_REQUIRED.value),
        (FailureClass.FC_4_UPSTREAM_PRECONDITION_EVIDENCE.value,CandidateMutationStanding.UNCHANGED.value,ProductionState.PR_14_REVIEW_EVIDENCE_REMEDIATION_REQUIRED.value),
        (FailureClass.FC_5_TRACEABILITY_ONLY.value,CandidateMutationStanding.UNCHANGED.value,ProductionState.PR_14_REVIEW_EVIDENCE_REMEDIATION_REQUIRED.value),
        (FailureClass.FC_5_TRACEABILITY_ONLY.value,CandidateMutationStanding.CANDIDATE_MUTATING.value,ProductionState.PR_11_IMPLEMENTATION_REPAIR_AUTHORIZED.value),
        (FailureClass.FC_6_EVIDENCE_ACCESS_TRANSPORT.value,CandidateMutationStanding.UNCHANGED.value,ProductionState.PR_14_REVIEW_EVIDENCE_REMEDIATION_REQUIRED.value),
        (FailureClass.FC_7_TEST_ENVIRONMENT_TOOLING.value,CandidateMutationStanding.UNCHANGED.value,ProductionState.PR_14_REVIEW_EVIDENCE_REMEDIATION_REQUIRED.value),
        (FailureClass.FC_8_PACKAGE_INTEGRITY.value,CandidateMutationStanding.CONTAINER_ONLY.value,ProductionState.PR_14_REVIEW_EVIDENCE_REMEDIATION_REQUIRED.value),
        (FailureClass.FC_8_PACKAGE_INTEGRITY.value,CandidateMutationStanding.LOGICAL_PAYLOAD_CHANGING.value,ProductionState.PR_11_IMPLEMENTATION_REPAIR_AUTHORIZED.value),
    ],
)
def test_all_implementation_failure_classes_route_to_frozen_pr_states(
    tmp_path: Path,failure_class: str,mutation: str,expected: str,
) -> None:
    s=service(tmp_path)
    candidate=build_candidate(s)
    review=s.review(
        candidate_id=candidate.candidate_id.value,reviewer_principal_id="reviewer",
        review_method="external_ai",verdict="fail",failure_class=failure_class,
        mutation_standing=mutation,authorized_reopen_scope=("targeted-item",),
    )
    run=s.store.get("production_run",f"production-run:{candidate.candidate_id.value}")
    assert run["current_state"] == expected
    assert review.verdict.value == "fail"


def test_inconclusive_requires_classification_and_reopen_scope(tmp_path: Path) -> None:
    s=service(tmp_path)
    candidate=build_candidate(s)
    with pytest.raises(PermissionError,match="FailureClassification"):
        s.review(
            candidate_id=candidate.candidate_id.value,reviewer_principal_id="reviewer",
            review_method="external_ai",verdict="inconclusive",
        )


def test_shared_module_change_cannot_be_relabelled_agent_specific(tmp_path: Path) -> None:
    s=service(tmp_path)
    with pytest.raises(PermissionError,match="SHARED_CHANGE_REQUIRED_STOP"):
        s.create_module_revision(
            module_id="shared",revision_id="shared-r1",name="Shared",content="print('x')",
            actor_principal_id="builder",module_type=ModuleType.SHARED_CAPABILITY_MODULE.value,
            authority_class=ModuleAuthorityClass.SHARED_CHANGE_REVIEW_REQUIRED.value,
            editability=ModuleEditability.REVIEW_GATED.value,
            agent_requirement_ref="req-1",agent_authority_boundary_ref="boundary-1",
        )


def test_backup_manifest_verification_and_restore_epoch_fence(tmp_path: Path) -> None:
    store=SQLiteStateStore(str(tmp_path/"backup.db"))
    with store.transaction():
        store.add("authority_projection","x",{"standing":"CURRENT"})
        store.publish_blob(b"exact-authoritative-bytes")
        store.append_audit(
            event_id="a1",actor_principal_id="p",action="commit",subject_kind="x",subject_id="1",
            metadata={},occurred_at=__import__("datetime").datetime.now(__import__("datetime").UTC),
        )
        manifest=store.create_backup_manifest("backup-1")
    assert manifest["standing"] == "RECORDED"
    assessment=store.verify_backup_manifest("backup-1")
    assert assessment["standing"] == "VERIFIED_RECOVERABLE"
    with store.transaction():
        assert store.advance_after_verified_restore("backup-1") == 2
    assert store.recovery_epoch() == 2


def _frozen_deployment(s: StudioService):
    candidate=build_candidate(s)
    review=s.review(candidate_id=candidate.candidate_id.value,reviewer_principal_id="reviewer",review_method="external_ai",passed=True)
    freeze=s.freeze(candidate_id=candidate.candidate_id.value,review_id=review.review_id,actor_principal_id="freezer")
    s.create_baseline(
        baseline_id="b1",lineage_id="lineage-1",frozen_artifact_id=freeze.frozen_artifact.id.value,
        expected_predecessor_baseline_id=None,actor_principal_id="promoter",
    )
    dep=s.authorize_deployment(
        deployment_id="d1",frozen_artifact_id=freeze.frozen_artifact.id.value,actor_principal_id="deployer",
        runtime_profile={"runtime":"python"},environment={"env":"test"},provider_binding={"provider":"test"},
        secret_scope={},permission_scope={"permissions":[]},
        policy={"authority_boundary":{"network":False}},runtime_boundary={"network":False},
    )
    return dep


def test_ambiguous_activation_requires_explicit_reconciliation(tmp_path: Path) -> None:
    s=service(tmp_path)
    dep=_frozen_deployment(s)
    attempt=s.begin_activation(deployment_id=dep.deployment_id,actor_principal_id="deployer")
    pending=s.reconcile_activation(
        activation_attempt_id=attempt,actor_principal_id="deployer",outcome="AMBIGUOUS",
        failure_reason="provider response lost",
    )
    assert pending.runtime_standing.value == "ACTIVATING"
    attempt_record=s.store.get("activation_attempt",attempt)
    assert attempt_record["standing"] == "AMBIGUOUS"
    active=s.reconcile_activation(
        activation_attempt_id=attempt,actor_principal_id="deployer",outcome="ACTIVATED",
        external_runtime_identity="provider-runtime-123",
    )
    assert active.runtime_standing.value == "ACTIVE"


def test_closed_control_plane_rejects_dynamic_operation_and_replays_idempotently(tmp_path: Path) -> None:
    s=service(tmp_path)
    dep=_frozen_deployment(s)
    cp=StudioControlPlane(s)
    unknown=cp.execute(CommandEnvelope(
        command_id="cmd-unknown",operation_descriptor_id="op:dynamic:invented",
        exact_target_ref=dep.deployment_id,principal_ref="deployer",workspace_ref="ws",
        idempotency_key="idem-u",expected_recovery_epoch=s.store.recovery_epoch(),payload={},
    ))
    assert unknown.standing == "REJECTED"
    cmd=CommandEnvelope(
        command_id="cmd-activate",operation_descriptor_id="op:deployment:activate-runtime",
        exact_target_ref=dep.deployment_id,principal_ref="deployer",workspace_ref="ws",
        idempotency_key="idem-a",expected_recovery_epoch=s.store.recovery_epoch(),payload={},
    )
    first=cp.execute(cmd)
    second=cp.execute(cmd)
    assert first.standing == "COMMITTED"
    assert second.standing == "REPLAYED"
    assert first.result_ref == second.result_ref


def test_pr15_stale_baseline_routes_to_pr15r_and_requires_reconciliation(tmp_path: Path) -> None:
    s=service(tmp_path)
    # Establish b1 as the locked predecessor for candidate 2.
    c1=build_candidate(s,"1")
    r1=s.review(candidate_id=c1.candidate_id.value,reviewer_principal_id="reviewer",review_method="external_ai",passed=True)
    f1=s.freeze(candidate_id=c1.candidate_id.value,review_id=r1.review_id,actor_principal_id="freezer")
    s.create_baseline(
        baseline_id="b1",lineage_id="lineage-1",frozen_artifact_id=f1.frozen_artifact.id.value,
        expected_predecessor_baseline_id=None,actor_principal_id="promoter",
    )

    s.create_module_revision(
        module_id="m2",revision_id="r2",name="M2",content="print('two')",
        actor_principal_id="builder",provided_capabilities=("answer",),identity_domain="d2",
    )
    s.compose("c2",["r2"],actor_principal_id="builder")
    _,c2=s.build(
        "c2",actor_principal_id="builder",workspace_id="ws",lineage_id="lineage-1",
        predecessor_baseline_id="b1",
    )
    r2=s.review(candidate_id=c2.candidate_id.value,reviewer_principal_id="reviewer",review_method="external_ai",passed=True)

    # Promote a different accepted lineage target after c2 review, making c2's locked predecessor stale.
    s.create_module_revision(
        module_id="m3",revision_id="r3",name="M3",content="print('three')",
        actor_principal_id="builder",provided_capabilities=("answer",),identity_domain="d3",
    )
    s.compose("c3",["r3"],actor_principal_id="builder")
    _,c3=s.build(
        "c3",actor_principal_id="builder",workspace_id="ws",lineage_id="lineage-1",
        predecessor_baseline_id="b1",
    )
    r3=s.review(candidate_id=c3.candidate_id.value,reviewer_principal_id="reviewer",review_method="external_ai",passed=True)
    f3=s.freeze(candidate_id=c3.candidate_id.value,review_id=r3.review_id,actor_principal_id="freezer")
    s.create_baseline(
        baseline_id="b2",lineage_id="lineage-1",frozen_artifact_id=f3.frozen_artifact.id.value,
        expected_predecessor_baseline_id="b1",actor_principal_id="promoter",
    )

    with pytest.raises(PermissionError,match="STALE_BASELINE"):
        s.freeze(candidate_id=c2.candidate_id.value,review_id=r2.review_id,actor_principal_id="freezer")
    run=s.store.get("production_run",f"production-run:{c2.candidate_id.value}")
    assert run["current_state"] == ProductionState.PR_15R_BASELINE_RECONCILIATION_REQUIRED.value
    reconciled=s.reconcile_stale_baseline(
        candidate_id=c2.candidate_id.value,actor_principal_id="builder",no_design_change=True,
    )
    assert reconciled.current_state is ProductionState.PR_09_IMPLEMENTATION_CANDIDATE


def test_superseded_active_deployment_enters_revalidation_and_can_be_denied(tmp_path: Path) -> None:
    s=service(tmp_path)
    dep=_frozen_deployment(s)
    active=s.activate_runtime(deployment_id=dep.deployment_id,actor_principal_id="deployer")
    assert active.runtime_standing.value == "ACTIVE"

    # Make another baseline current on the same lineage.
    s.create_module_revision(
        module_id="next",revision_id="next-r",name="Next",content="print('next')",
        actor_principal_id="builder",provided_capabilities=("answer",),identity_domain="next",
    )
    s.compose("next-c",["next-r"],actor_principal_id="builder")
    _,cand=s.build(
        "next-c",actor_principal_id="builder",workspace_id="ws",lineage_id="lineage-1",
        predecessor_baseline_id="b1",
    )
    rev=s.review(candidate_id=cand.candidate_id.value,reviewer_principal_id="reviewer",review_method="external_ai",passed=True)
    frz=s.freeze(candidate_id=cand.candidate_id.value,review_id=rev.review_id,actor_principal_id="freezer")
    s.create_baseline(
        baseline_id="b2",lineage_id="lineage-1",frozen_artifact_id=frz.frozen_artifact.id.value,
        expected_predecessor_baseline_id="b1",actor_principal_id="promoter",
    )
    stale=s._deployment_from(s.store.get("deployment","d1"))
    assert stale.grant_standing.value == "SUPERSEDED_TARGET_REVALIDATION_REQUIRED"
    assert stale.runtime_standing.value == "REVALIDATION_REQUIRED"
    denied=s.revalidate_deployment(deployment_id="d1",actor_principal_id="deployer",continue_active=True)
    assert denied.runtime_standing.value == "REVALIDATION_REQUIRED"

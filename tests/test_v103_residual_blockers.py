from __future__ import annotations

from pathlib import Path

import pytest

from ra_agent_studio.api import app
from ra_agent_studio.application.control_contracts import CommandEnvelope
from ra_agent_studio.application.control_plane import StudioControlPlane
from ra_agent_studio.application.studio import StudioService
from ra_agent_studio.domain.auth import AuthorityGrant, AuthorityScope, Principal
from tests.support import (
    AmbiguousTestRuntimeLauncher,
    ContractTestFactoryRuntime,
    ContractTestRuntimeLauncher,
    authority_registry,
)


def service(tmp_path: Path, *, ambiguous_runtime: bool = False) -> StudioService:
    return StudioService(
        db_path=str(tmp_path / "v103.db"),
        authority_registry=authority_registry(),
        factory_runtime=ContractTestFactoryRuntime(),
        runtime_launcher=(
            AmbiguousTestRuntimeLauncher()
            if ambiguous_runtime else
            ContractTestRuntimeLauncher()
        ),
    )


def candidate(s: StudioService, *, suffix: str = "1", predecessor: str | None = None):
    s.create_module_revision(
        module_id=f"v103-m-{suffix}",
        revision_id=f"v103-r-{suffix}",
        name=f"V103 {suffix}",
        content="print('v103')",
        actor_principal_id="builder",
        provided_capabilities=("answer",),
        identity_domain=f"v103-domain-{suffix}",
    )
    s.compose(f"v103-c-{suffix}", [f"v103-r-{suffix}"], actor_principal_id="builder")
    return s.build(
        f"v103-c-{suffix}",
        actor_principal_id="builder",
        workspace_id="ws",
        lineage_id="v103-lineage",
        predecessor_baseline_id=predecessor,
    )[1]


def frozen_deployment(s: StudioService):
    cand=candidate(s)
    review=s.review(
        candidate_id=cand.candidate_id.value,
        reviewer_principal_id="reviewer",
        review_method="external_ai",
        passed=True,
    )
    freeze=s.freeze(
        candidate_id=cand.candidate_id.value,
        review_id=review.review_id,
        actor_principal_id="freezer",
    )
    s.create_baseline(
        baseline_id="v103-b1",
        lineage_id="v103-lineage",
        frozen_artifact_id=freeze.frozen_artifact.id.value,
        expected_predecessor_baseline_id=None,
        actor_principal_id="promoter",
    )
    dep=s.authorize_deployment(
        deployment_id="v103-d1",
        frozen_artifact_id=freeze.frozen_artifact.id.value,
        actor_principal_id="deployer",
        runtime_profile={"runtime":"python"},
        environment={"env":"test"},
        provider_binding={"provider":"contract-test"},
        secret_scope={},
        permission_scope={"permissions":[]},
        policy={"authority_boundary":{"network":False}},
        runtime_boundary={"network":False},
    )
    return cand,freeze,dep


def test_st2_b01_lock_precedes_currentness_and_is_continuous_to_promotion(tmp_path: Path) -> None:
    s=service(tmp_path)
    cand=candidate(s)
    review=s.review(
        candidate_id=cand.candidate_id.value,
        reviewer_principal_id="reviewer",
        review_method="external_ai",
        passed=True,
    )
    freeze=s.freeze(
        candidate_id=cand.candidate_id.value,
        review_id=review.review_id,
        actor_principal_id="freezer",
    )
    closure=s.store.get_immutable("freeze_closure",freeze.frozen_artifact.id.value)
    assert closure["predecessor_currentness_assessed_under_lock"] is True
    lock=s.store.promotion_lock("v103-lineage")
    assert lock is not None
    assert lock["holder"] == closure["canonical_promotion_lock_holder"]
    assert int(lock["fencing_token"]) == int(closure["canonical_promotion_fencing_token"])

    s.create_baseline(
        baseline_id="v103-b1",
        lineage_id="v103-lineage",
        frozen_artifact_id=freeze.frozen_artifact.id.value,
        expected_predecessor_baseline_id=None,
        actor_principal_id="promoter",
    )
    released=s.store.promotion_lock("v103-lineage")
    assert released is not None
    assert released["holder"] == ""


def test_st2_b02_only_commands_is_public_mutation_api() -> None:
    post_routes={
        route.path
        for route in app.routes
        if "POST" in getattr(route,"methods",set())
    }
    assert post_routes == {"/commands"}


def test_st2_b03_authority_mutation_and_idempotency_rollback_together(tmp_path: Path, monkeypatch) -> None:
    s=service(tmp_path)
    cp=StudioControlPlane(s)
    original=s.store.add_immutable

    def fail_command_commit(kind: str, key: str, payload: dict):
        if kind == "command_commit":
            raise RuntimeError("simulated crash before authoritative commit")
        return original(kind,key,payload)

    monkeypatch.setattr(s.store,"add_immutable",fail_command_commit)
    command=CommandEnvelope(
        command_id="v103-atomic-cmd",
        operation_descriptor_id="op:factory:module-revision-create",
        exact_target_ref="v103-atomic-r1",
        principal_ref="builder",
        workspace_ref="ws",
        idempotency_key="v103-atomic-idem",
        expected_recovery_epoch=s.store.recovery_epoch(),
        payload={
            "module_id":"v103-atomic-m1",
            "name":"Atomic",
            "content":"print('atomic')",
        },
    )
    result=cp.execute(command)
    assert result.standing == "REJECTED"
    with pytest.raises(KeyError):
        s.store.get("module","v103-atomic-r1")
    assert s.store.get_idempotency("v103-atomic-cmd") is None


def test_st2_b04_activation_uses_durable_attempt_and_preserves_ambiguous(tmp_path: Path) -> None:
    s=service(tmp_path,ambiguous_runtime=True)
    _,_,dep=frozen_deployment(s)
    cp=StudioControlPlane(s)
    command=CommandEnvelope(
        command_id="v103-activate-cmd",
        operation_descriptor_id="op:deployment:activate-runtime",
        exact_target_ref=dep.deployment_id,
        principal_ref="deployer",
        workspace_ref="ws",
        idempotency_key="v103-activate-idem",
        expected_recovery_epoch=s.store.recovery_epoch(),
        payload={},
    )
    first=cp.execute(command)
    assert first.standing == "COMMITTED"
    assert first.payload["runtime_standing"] == "ACTIVATING"
    attempt=s.store.get("activation_attempt",first.result_ref)
    assert attempt["standing"] == "AMBIGUOUS"
    assert s.store.get_idempotency("v103-activate-cmd")["result_key"] == first.result_ref

    second=cp.execute(command)
    assert second.standing == "REPLAYED"
    assert second.result_ref == first.result_ref
    assert second.payload["runtime_standing"] == "ACTIVATING"


def test_st2_b04_confirmed_provider_is_required_for_active_and_stopped(tmp_path: Path) -> None:
    s=service(tmp_path)
    _,_,dep=frozen_deployment(s)
    cp=StudioControlPlane(s)
    activate=cp.execute(CommandEnvelope(
        command_id="v103-active-cmd",
        operation_descriptor_id="op:deployment:activate-runtime",
        exact_target_ref=dep.deployment_id,
        principal_ref="deployer",
        workspace_ref="ws",
        idempotency_key="v103-active-idem",
        expected_recovery_epoch=s.store.recovery_epoch(),
        payload={},
    ))
    assert activate.payload["runtime_standing"] == "ACTIVE"

    stop=cp.execute(CommandEnvelope(
        command_id="v103-stop-cmd",
        operation_descriptor_id="op:deployment:stop-runtime",
        exact_target_ref=dep.deployment_id,
        principal_ref="deployer",
        workspace_ref="ws",
        idempotency_key="v103-stop-idem",
        expected_recovery_epoch=s.store.recovery_epoch(),
        payload={},
    ))
    assert stop.payload["runtime_standing"] == "STOPPED"
    stop_attempt=s.store.get("stop_attempt",stop.result_ref)
    assert stop_attempt["standing"] == "STOPPED"


def test_st2_b05_authentication_is_not_authoring_authority(tmp_path: Path) -> None:
    s=service(tmp_path)
    s.authority.add_principal(Principal("authenticated-only","ws"),bearer_token="auth-only-token")
    with pytest.raises(PermissionError,match="implementation_authoring authority"):
        s.create_module_revision(
            module_id="unauthorized-m",
            revision_id="unauthorized-r",
            name="No Authority",
            content="print('no')",
            actor_principal_id="authenticated-only",
        )

    s.authority.add_principal(Principal("implementation-only","ws"),bearer_token="impl-only-token")
    s.authority.add_grant(AuthorityGrant(
        "impl-only-grant",
        "implementation-only",
        frozenset({AuthorityScope.IMPLEMENTATION_AUTHORING}),
        "ws",
    ))
    s.create_module_revision(
        module_id="impl-m",
        revision_id="impl-r",
        name="Impl",
        content="print('impl')",
        actor_principal_id="implementation-only",
    )
    with pytest.raises(PermissionError,match="design_authoring authority"):
        s.compose("unauthorized-design",["impl-r"],actor_principal_id="implementation-only")

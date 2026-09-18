from __future__ import annotations

from pathlib import Path

import pytest

from ra_agent_studio.application.studio import StudioService
from ra_agent_studio.domain.auth import AuthorityGrant, AuthorityScope, Principal
from ra_agent_studio.domain.effect import EffectFixture
from tests.support import ContractTestFactoryRuntime, authority_registry


def studio(tmp_path: Path) -> StudioService:
    return StudioService(
        db_path=str(tmp_path / "studio.db"),
        authority_registry=authority_registry(),
        factory_runtime=ContractTestFactoryRuntime(),
    )


def add_executable_module(service: StudioService, *, revision_id: str, prefix: str, predecessor: str | None = None):
    code = f"import sys\nprint('{prefix}:' + sys.stdin.read())\n"
    return service.create_module_revision(
        module_id=f"module-{revision_id}",
        revision_id=revision_id,
        name=f"Module {revision_id}",
        content=code,
        actor_principal_id="builder",
        predecessor_revision_id=predecessor,
        provided_capabilities=("answer",),
        identity_domain=f"domain-{revision_id}",
        config_json='{"mode":"test"}',
    )


def build_candidate(service: StudioService, *, revision_id: str, composition_id: str, predecessor_baseline_id: str | None = None):
    service.compose(composition_id, [revision_id], actor_principal_id="builder")
    return service.build(
        composition_id,
        actor_principal_id="builder",
        workspace_id="ws",
        lineage_id="lineage-1",
        predecessor_baseline_id=predecessor_baseline_id,
    )[1]


def test_review_cannot_be_manufactured_from_two_names(tmp_path: Path) -> None:
    service = studio(tmp_path)
    add_executable_module(service, revision_id="r1", prefix="A")
    candidate = build_candidate(service, revision_id="r1", composition_id="c1")

    service.authority.add_principal(Principal("fake-reviewer", "ws"))
    with pytest.raises(PermissionError, match="lacks review authority"):
        service.review(
            candidate_id=candidate.candidate_id.value,
            reviewer_principal_id="fake-reviewer",
            review_method="external_ai",
            passed=True,
        )


def test_review_requires_method_scope_workspace_and_contribution_independence(tmp_path: Path) -> None:
    service = studio(tmp_path)
    add_executable_module(service, revision_id="r1", prefix="A")
    candidate = build_candidate(service, revision_id="r1", composition_id="c1")

    with pytest.raises(PermissionError):
        service.review(
            candidate_id=candidate.candidate_id.value,
            reviewer_principal_id="reviewer",
            review_method="unapproved_method",
            passed=True,
        )

    service.authority.add_principal(Principal("contributor-reviewer", "ws"))
    service.authority.add_grant(
        AuthorityGrant(
            "bad-review-grant",
            "contributor-reviewer",
            frozenset({AuthorityScope.REVIEW}),
            "ws",
            review_methods=frozenset({"external_ai"}),
            independent_of_principals=frozenset(),
        )
    )
    with pytest.raises(PermissionError, match="workspace contributed|does not attest principal contribution independence"):
        service.review(
            candidate_id=candidate.candidate_id.value,
            reviewer_principal_id="contributor-reviewer",
            review_method="external_ai",
            passed=True,
        )


def test_pass_review_is_exactly_bound_to_candidate_hash(tmp_path: Path) -> None:
    service = studio(tmp_path)
    add_executable_module(service, revision_id="r1", prefix="A")
    add_executable_module(service, revision_id="r2", prefix="B")
    candidate1 = build_candidate(service, revision_id="r1", composition_id="c1")
    candidate2 = build_candidate(service, revision_id="r2", composition_id="c2")
    review = service.review(
        candidate_id=candidate1.candidate_id.value,
        reviewer_principal_id="reviewer",
        review_method="external_ai",
        passed=True,
    )
    with pytest.raises(PermissionError, match="not bound to this exact candidate"):
        service.freeze(
            candidate_id=candidate2.candidate_id.value,
            review_id=review.review_id,
            actor_principal_id="freezer",
        )


def test_authoritative_records_survive_restart(tmp_path: Path) -> None:
    db_path = tmp_path / "persistent.db"
    registry = authority_registry()
    first = StudioService(
        db_path=str(db_path), authority_registry=registry, factory_runtime=ContractTestFactoryRuntime()
    )
    add_executable_module(first, revision_id="r1", prefix="A")
    candidate = build_candidate(first, revision_id="r1", composition_id="c1")
    review = first.review(
        candidate_id=candidate.candidate_id.value,
        reviewer_principal_id="reviewer",
        review_method="external_ai",
        passed=True,
    )
    freeze = first.freeze(
        candidate_id=candidate.candidate_id.value,
        review_id=review.review_id,
        actor_principal_id="freezer",
    )
    baseline = first.create_baseline(
        baseline_id="b1",
        lineage_id="lineage-1",
        frozen_artifact_id=freeze.frozen_artifact.id.value,
        expected_predecessor_baseline_id=None,
        actor_principal_id="promoter",
    )
    first.authorize_deployment(
        deployment_id="d1", frozen_artifact_id=freeze.frozen_artifact.id.value,
        actor_principal_id="deployer", runtime_profile={"runtime":"python-3.14"},
        environment={"env":"test"}, provider_binding={"provider":"test"}, secret_scope={},
        permission_scope={"permissions":[]}, policy={"authority_boundary":{"network":False}},
        runtime_boundary={"network":False},
    )
    first.activate_runtime(deployment_id="d1", actor_principal_id="deployer")
    first.store.close()

    second = StudioService(
        db_path=str(db_path), authority_registry=registry, factory_runtime=ContractTestFactoryRuntime()
    )
    snapshot = second.snapshot()
    assert snapshot["reviews"][0]["review_id"] == review.review_id
    assert snapshot["freezes"][0]["frozen_artifact_id"] == freeze.frozen_artifact.id.value
    assert snapshot["baselines"][0]["baseline_id"] == baseline.baseline_id.value
    assert snapshot["deployments"][0]["deployment_id"] == "d1"
    assert any(event["action"] == "runtime_activated" for event in snapshot["audit"])


def test_effect_sandbox_executes_real_module_and_computes_delta(tmp_path: Path) -> None:
    service = studio(tmp_path)
    add_executable_module(service, revision_id="r1", prefix="BEFORE")
    add_executable_module(service, revision_id="r2", prefix="AFTER")
    fixture = EffectFixture("fx", "hello", ("hello",))
    delta = service.compare_effect_fixture("r1", "r2", fixture)
    assert delta.before_output.strip() == "BEFORE:hello"
    assert delta.after_output.strip() == "AFTER:hello"
    assert delta.changed is True
    assert delta.before_passed and delta.after_passed


def test_freeze_promotion_and_deployment_are_distinct_authority_transitions(tmp_path: Path) -> None:
    service = studio(tmp_path)
    add_executable_module(service, revision_id="r1", prefix="A")
    c1 = build_candidate(service, revision_id="r1", composition_id="c1")
    r1 = service.review(
        candidate_id=c1.candidate_id.value,
        reviewer_principal_id="reviewer",
        review_method="external_ai",
        passed=True,
    )
    f1 = service.freeze(candidate_id=c1.candidate_id.value, review_id=r1.review_id, actor_principal_id="freezer")
    service.create_baseline(
        baseline_id="b1",
        lineage_id="lineage-1",
        frozen_artifact_id=f1.frozen_artifact.id.value,
        expected_predecessor_baseline_id=None,
        actor_principal_id="promoter",
    )

    add_executable_module(service, revision_id="r2", prefix="B")
    c2 = build_candidate(service, revision_id="r2", composition_id="c2", predecessor_baseline_id="b1")
    r2 = service.review(
        candidate_id=c2.candidate_id.value,
        reviewer_principal_id="reviewer",
        review_method="external_ai",
        passed=True,
    )
    f2 = service.freeze(candidate_id=c2.candidate_id.value, review_id=r2.review_id, actor_principal_id="freezer")

    with pytest.raises(PermissionError, match="promotion is stale"):
        service.create_baseline(
            baseline_id="b2-stale",
            lineage_id="lineage-1",
            frozen_artifact_id=f2.frozen_artifact.id.value,
            expected_predecessor_baseline_id=None,
            actor_principal_id="promoter",
        )

    service.create_baseline(
        baseline_id="b2",
        lineage_id="lineage-1",
        frozen_artifact_id=f2.frozen_artifact.id.value,
        expected_predecessor_baseline_id="b1",
        actor_principal_id="promoter",
    )
    with pytest.raises(PermissionError, match="not canonical current baseline"):
        service.authorize_deployment(
            deployment_id="d-old", frozen_artifact_id=f1.frozen_artifact.id.value,
            actor_principal_id="deployer", runtime_profile={"runtime":"python"},
            environment={"env":"test"}, provider_binding={"provider":"test"}, secret_scope={},
            permission_scope={"permissions":[]}, policy={"authority_boundary":{"network":False}},
            runtime_boundary={"network":False},
        )
    deployment = service.authorize_deployment(
        deployment_id="d-current", frozen_artifact_id=f2.frozen_artifact.id.value,
        actor_principal_id="deployer", runtime_profile={"runtime":"python"},
        environment={"env":"test"}, provider_binding={"provider":"test"}, secret_scope={},
        permission_scope={"permissions":[]}, policy={"authority_boundary":{"network":False}},
        runtime_boundary={"network":False},
    )
    deployment = service.activate_runtime(deployment_id="d-current", actor_principal_id="deployer")
    assert deployment.baseline_id == "b2"
    assert deployment.runtime_standing.value == "ACTIVE"
    held = service.place_safety_hold(deployment_id="d-current", actor_principal_id="deployer")
    assert held.safety_hold is True
    revoked = service.revoke_deployment(deployment_id="d-current", actor_principal_id="deployer", reason="test revoke")
    assert revoked.grant_standing.value == "REVOKED"


def test_same_target_review_requires_workspace_independence(tmp_path: Path) -> None:
    service = studio(tmp_path)
    add_executable_module(service, revision_id="rw1", prefix="A")
    candidate = build_candidate(service, revision_id="rw1", composition_id="cw1")
    service.authority.add_principal(Principal("same-workspace-reviewer", "ws"))
    service.authority.add_grant(
        AuthorityGrant(
            "same-workspace-review-grant",
            "same-workspace-reviewer",
            frozenset({AuthorityScope.REVIEW}),
            "ws",
            review_methods=frozenset({"external_ai"}),
            independent_of_principals=frozenset({"builder"}),
            independent_of_workspaces=frozenset({"ws"}),
            authority_source="external-review-authority",
            target_scope="exact_candidate_in_workspace",
        )
    )
    with pytest.raises(PermissionError, match="reviewer workspace contributed"):
        service.review(
            candidate_id=candidate.candidate_id.value,
            reviewer_principal_id="same-workspace-reviewer",
            review_method="external_ai",
            passed=True,
        )


def test_controlled_execution_blocks_host_secret_and_network(tmp_path: Path, monkeypatch) -> None:
    service = studio(tmp_path)
    secret_name = "RA_STUDIO_HOST_SECRET_FOR_TEST"
    monkeypatch.setenv(secret_name, "must-not-leak")
    code = (
        "import os, socket\n"
        "print('secret=' + str(os.environ.get('" + secret_name + "')))\n"
        "s=socket.socket(); s.settimeout(0.5)\n"
        "try:\n"
        "    s.connect(('1.1.1.1', 53)); print('network=OPEN')\n"
        "except Exception:\n"
        "    print('network=BLOCKED')\n"
    )
    service.create_module_revision(
        module_id="hostile", revision_id="hostile-r1", name="Hostile",
        content=code, actor_principal_id="builder",
        provided_capabilities=("answer",), identity_domain="hostile",
        config_json='{"mode":"hostile"}',
    )
    obs = service.run_effect_fixture("hostile-r1", EffectFixture("fx-hostile", "", ("secret=None", "network=BLOCKED")))
    assert obs.passed is True


def test_closed_operation_catalog_requires_recovery_and_idempotency() -> None:
    from ra_agent_studio.application.control_contracts import CommandEnvelope
    from ra_agent_studio.application.operation_catalog import APPLICATION_OPERATION_CATALOG, descriptor

    assert "op:governance:implementation-review-pass" in APPLICATION_OPERATION_CATALOG
    assert "op:factory:exact-freeze" in APPLICATION_OPERATION_CATALOG
    assert descriptor("op:factory:canonical-promote").intent == "CANONICAL_PROMOTE"
    with pytest.raises(ValueError, match="IDEMPOTENCY_KEY_REQUIRED"):
        CommandEnvelope(
            command_id="c1", operation_descriptor_id="op:factory:exact-freeze",
            exact_target_ref="candidate:x", principal_ref="freezer", workspace_ref="ws",
            idempotency_key="", expected_recovery_epoch=1,
        ).validate()
    with pytest.raises(ValueError, match="EXPECTED_RECOVERY_EPOCH_REQUIRED"):
        CommandEnvelope(
            command_id="c2", operation_descriptor_id="op:factory:exact-freeze",
            exact_target_ref="candidate:x", principal_ref="freezer", workspace_ref="ws",
            idempotency_key="idem", expected_recovery_epoch=0,
        ).validate()

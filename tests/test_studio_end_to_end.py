from pathlib import Path

from ra_agent_studio.application.studio import StudioService
from ra_agent_studio.domain.effect import EffectFixture
from tests.support import ContractTestFactoryRuntime, ContractTestRuntimeLauncher, authority_registry


def test_studio_happy_path_through_deployment(tmp_path: Path) -> None:
    studio = StudioService(
        db_path=str(tmp_path / "studio.db"),
        authority_registry=authority_registry(),
        factory_runtime=ContractTestFactoryRuntime(),
        runtime_launcher=ContractTestRuntimeLauncher(),
    )
    studio.create_module_revision(
        module_id="researcher",
        revision_id="r1",
        name="Researcher",
        content="import sys\nprint('evidence:' + sys.stdin.read())\n",
        actor_principal_id="builder",
        provided_capabilities=("evidence",),
        identity_domain="research",
    )
    studio.prepare_candidate("r1", actor_principal_id="builder")
    observation = studio.run_effect_fixture("r1", EffectFixture("fx1", "question", ("evidence",)))
    assert observation.passed is True

    composition = studio.compose("comp1", ["r1"], actor_principal_id="builder")
    evidence, candidate = studio.build(
        "comp1",
        actor_principal_id="builder",
        workspace_id="ws",
        lineage_id="lineage-1",
    )
    assert evidence.reproducible is True
    assert candidate.candidate_hash == evidence.artifact_hash

    review = studio.review(
        candidate_id=candidate.candidate_id.value,
        reviewer_principal_id="reviewer",
        review_method="external_ai",
        passed=True,
    )
    freeze = studio.freeze(
        candidate_id=candidate.candidate_id.value,
        review_id=review.review_id,
        actor_principal_id="freezer",
    )
    baseline = studio.create_baseline(
        baseline_id="baseline-1",
        lineage_id="lineage-1",
        frozen_artifact_id=freeze.frozen_artifact.id.value,
        expected_predecessor_baseline_id=None,
        actor_principal_id="promoter",
    )
    deployment = studio.authorize_deployment(
        deployment_id="deployment-1", frozen_artifact_id=freeze.frozen_artifact.id.value,
        actor_principal_id="deployer",
        runtime_profile={"runtime":"python-3.14"}, environment={"env":"test"},
        provider_binding={"provider":"local-test"}, secret_scope={},
        permission_scope={"permissions":[]},
        policy={"authority_boundary":{"network":False,"tools":[]}},
        runtime_boundary={"network":False,"tools":[]},
    )
    deployment = studio.launch_runtime(deployment_id="deployment-1", actor_principal_id="deployer")

    assert baseline.frozen_artifact_id == freeze.frozen_artifact.id
    assert deployment.frozen_artifact_id == freeze.frozen_artifact.id.value
    assert deployment.baseline_id == baseline.baseline_id.value
    assert deployment.runtime_standing.value == "ACTIVE"


def test_ungranted_principal_cannot_review(tmp_path: Path) -> None:
    registry = authority_registry()
    studio = StudioService(
        db_path=str(tmp_path / "studio.db"),
        authority_registry=registry,
        factory_runtime=ContractTestFactoryRuntime(),
        runtime_launcher=ContractTestRuntimeLauncher(),
    )
    studio.create_module_revision(
        module_id="m",
        revision_id="r",
        name="M",
        content="print('ok')",
        actor_principal_id="builder",
        identity_domain="m",
    )
    studio.compose("c", ["r"], actor_principal_id="builder")
    _, candidate = studio.build("c", actor_principal_id="builder", workspace_id="ws", lineage_id="lineage-1")
    try:
        studio.review(
            candidate_id=candidate.candidate_id.value,
            reviewer_principal_id="builder",
            review_method="external_ai",
            passed=True,
        )
    except PermissionError:
        pass
    else:
        raise AssertionError("principal without independent review authority was accepted")

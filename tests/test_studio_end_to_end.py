from ra_agent_studio.application.studio import StudioService
from ra_agent_studio.domain.effect import EffectFixture


def test_studio_happy_path_through_deployment() -> None:
    studio = StudioService()
    revision = studio.create_module_revision(
        module_id="researcher", revision_id="r1", name="Researcher", content="produce evidence"
    )
    candidate = studio.prepare_candidate("r1")
    observation = studio.run_effect_fixture("r1", EffectFixture("fx1", "question", ("evidence",)))
    assert observation.passed is True

    composition = studio.compose("comp1", ["r1"])
    evidence = studio.build("comp1")
    assert evidence.reproducible is True

    review = studio.review(subject_id=evidence.evidence_id, author_id="builder", reviewer_id="reviewer", passed=True)
    freeze = studio.freeze(candidate_id="candidate-comp1", candidate_hash=evidence.artifact_hash.value, review_id=review.review_id)
    baseline = studio.create_baseline(
        baseline_id="baseline-1", lineage_id="lineage-1", frozen_artifact_id=freeze.frozen_artifact.id.value
    )
    deployment = studio.deploy(deployment_id="deployment-1", frozen_artifact_id=freeze.frozen_artifact.id.value)

    assert baseline.frozen_artifact_id == freeze.frozen_artifact.id
    assert deployment.artifact_id == freeze.frozen_artifact.id


def test_review_must_be_independent() -> None:
    studio = StudioService()
    try:
        studio.review(subject_id="x", author_id="same", reviewer_id="same", passed=True)
    except PermissionError:
        pass
    else:
        raise AssertionError("non-independent review was accepted")
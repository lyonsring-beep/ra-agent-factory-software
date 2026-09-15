import pytest

from ra_agent_studio.domain.authority import Candidate, FrozenArtifact, require_deployable
from ra_agent_studio.domain.identity import CandidateId, FrozenArtifactId


def test_candidate_cannot_enter_deployment_path() -> None:
    candidate = Candidate(CandidateId("candidate-001"), approved=True)
    with pytest.raises(PermissionError):
        require_deployable(candidate)


def test_only_frozen_artifact_can_enter_deployment_path() -> None:
    artifact = FrozenArtifact(
        id=FrozenArtifactId("frozen-001"),
        source_candidate_id=CandidateId("candidate-001"),
    )
    assert require_deployable(artifact) is artifact

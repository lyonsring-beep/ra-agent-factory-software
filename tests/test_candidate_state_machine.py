import pytest

from ra_agent_studio.domain.identity import CandidateId, FrozenArtifactId
from ra_agent_studio.domain.state import (
    CandidateState,
    CandidateStateRecord,
    transition_candidate,
)


def test_review_pass_does_not_equal_freeze() -> None:
    current = CandidateStateRecord(CandidateId("candidate-1"), CandidateState.READY_FOR_REVIEW)
    reviewed = transition_candidate(current, CandidateState.REVIEW_PASSED)
    assert reviewed.state is CandidateState.REVIEW_PASSED
    assert reviewed.frozen_artifact_id is None


def test_freeze_requires_exact_frozen_artifact_identity() -> None:
    current = CandidateStateRecord(CandidateId("candidate-1"), CandidateState.REVIEW_PASSED)
    with pytest.raises(ValueError):
        transition_candidate(current, CandidateState.FROZEN)


def test_freeze_from_review_pass_is_allowed_with_identity() -> None:
    current = CandidateStateRecord(CandidateId("candidate-1"), CandidateState.REVIEW_PASSED)
    frozen = transition_candidate(
        current,
        CandidateState.FROZEN,
        frozen_artifact_id=FrozenArtifactId("frozen-1"),
    )
    assert frozen.state is CandidateState.FROZEN
    assert frozen.frozen_artifact_id == FrozenArtifactId("frozen-1")


def test_illegal_shortcut_from_draft_to_frozen_is_blocked() -> None:
    current = CandidateStateRecord(CandidateId("candidate-1"), CandidateState.DRAFT)
    with pytest.raises(ValueError):
        transition_candidate(
            current,
            CandidateState.FROZEN,
            frozen_artifact_id=FrozenArtifactId("frozen-1"),
        )

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from .identity import CandidateId, FrozenArtifactId


class CandidateState(StrEnum):
    DRAFT = "draft"
    READY_FOR_REVIEW = "ready_for_review"
    REVIEW_PASSED = "review_passed"
    REVIEW_FAILED = "review_failed"
    FROZEN = "frozen"


_ALLOWED_TRANSITIONS: dict[CandidateState, set[CandidateState]] = {
    CandidateState.DRAFT: {CandidateState.READY_FOR_REVIEW},
    CandidateState.READY_FOR_REVIEW: {
        CandidateState.REVIEW_PASSED,
        CandidateState.REVIEW_FAILED,
    },
    CandidateState.REVIEW_FAILED: {CandidateState.DRAFT},
    CandidateState.REVIEW_PASSED: {CandidateState.FROZEN},
    CandidateState.FROZEN: set(),
}


@dataclass(frozen=True, slots=True)
class CandidateStateRecord:
    candidate_id: CandidateId
    state: CandidateState
    frozen_artifact_id: FrozenArtifactId | None = None


def transition_candidate(
    current: CandidateStateRecord,
    target: CandidateState,
    *,
    frozen_artifact_id: FrozenArtifactId | None = None,
) -> CandidateStateRecord:
    if target not in _ALLOWED_TRANSITIONS[current.state]:
        raise ValueError(f"illegal candidate transition: {current.state} -> {target}")
    if target is CandidateState.FROZEN and frozen_artifact_id is None:
        raise ValueError("freeze transition requires frozen_artifact_id")
    if target is not CandidateState.FROZEN and frozen_artifact_id is not None:
        raise ValueError("frozen_artifact_id is valid only for the freeze transition")
    return CandidateStateRecord(
        candidate_id=current.candidate_id,
        state=target,
        frozen_artifact_id=frozen_artifact_id,
    )

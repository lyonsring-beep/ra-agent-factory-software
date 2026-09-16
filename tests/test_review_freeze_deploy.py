from datetime import UTC, datetime

import pytest

from ra_agent_studio.domain.governance import freeze_candidate
from ra_agent_studio.domain.identity import CandidateId, ContentHash, FrozenArtifactId
from ra_agent_studio.domain.review import ReviewRecord, ReviewVerdict


def test_failed_review_cannot_freeze() -> None:
    review = ReviewRecord("review-1", "subject-1", "reviewer", ReviewVerdict.FAIL)
    with pytest.raises(PermissionError):
        freeze_candidate(
            candidate_id=CandidateId("candidate-1"),
            candidate_hash=ContentHash.from_bytes(b"candidate"),
            frozen_artifact_id=FrozenArtifactId("frozen-1"),
            review=review,
            frozen_at=datetime.now(UTC),
        )


def test_passed_review_is_freeze_eligible_but_not_itself_frozen() -> None:
    review = ReviewRecord("review-1", "subject-1", "reviewer", ReviewVerdict.PASS)
    assert review.freeze_eligible is True
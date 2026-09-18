from datetime import UTC, datetime

import pytest

from ra_agent_studio.domain.authority import FrozenArtifact
from ra_agent_studio.domain.candidate import CandidateRecord
from ra_agent_studio.domain.governance import freeze_candidate
from ra_agent_studio.domain.identity import CandidateId, ContentHash, FrozenArtifactId, LineageId
from ra_agent_studio.domain.review import ReviewRecord, ReviewVerdict


def candidate(candidate_id: str, payload: bytes) -> CandidateRecord:
    digest = ContentHash.from_bytes(payload)
    return CandidateRecord(
        candidate_id=CandidateId(candidate_id),
        candidate_hash=digest,
        composition_id="comp",
        composition_hash=ContentHash.from_bytes(b"comp"),
        factory_evidence_id="evidence-1",
        factory_runtime_commit="factory-commit",
        factory_candidate_sha256="factory-candidate",
        author_principal_id="author",
        contributor_principal_ids=frozenset({"author"}),
        workspace_id="ws",
        lineage_id=LineageId("lineage"),
        predecessor_baseline_id=None,
    )


def review_for(item: CandidateRecord, verdict: ReviewVerdict) -> ReviewRecord:
    return ReviewRecord(
        review_id="review-1",
        subject_candidate_id=item.candidate_id,
        subject_hash=item.candidate_hash,
        reviewer_principal_id="reviewer",
        reviewer_workspace_id="review-ws",
        authority_grant_id="grant-review",
        authority_source="external-review-authority",
        review_method="external_ai",
        scope="exact_candidate",
        target_workspace_id="ws",
        verdict=verdict,
    )


def test_failed_review_cannot_freeze() -> None:
    item = candidate("candidate-1", b"candidate")
    with pytest.raises(PermissionError):
        freeze_candidate(
            candidate=item,
            frozen_artifact_id=FrozenArtifactId("frozen-1"),
            review=review_for(item, ReviewVerdict.FAIL),
            authority_grant_id="grant-freeze",
            frozen_by_principal_id="freezer",
            frozen_at=datetime.now(UTC),
        )


def test_passed_review_is_exact_hash_eligible_but_not_itself_frozen() -> None:
    item = candidate("candidate-1", b"candidate")
    review = review_for(item, ReviewVerdict.PASS)
    assert review.freeze_eligible is True
    assert not isinstance(review, FrozenArtifact)


def test_review_for_different_candidate_cannot_freeze() -> None:
    first = candidate("candidate-1", b"one")
    second = candidate("candidate-2", b"two")
    with pytest.raises(PermissionError, match="not bound"):
        freeze_candidate(
            candidate=second,
            frozen_artifact_id=FrozenArtifactId("frozen-2"),
            review=review_for(first, ReviewVerdict.PASS),
            authority_grant_id="grant-freeze",
            frozen_by_principal_id="freezer",
            frozen_at=datetime.now(UTC),
        )

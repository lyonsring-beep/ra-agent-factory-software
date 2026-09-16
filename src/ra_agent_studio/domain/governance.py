from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from .authority import DeploymentRecord, FrozenArtifact
from .identity import BaselineId, CandidateId, ContentHash, DeploymentId, FrozenArtifactId, LineageId
from .review import ReviewRecord


@dataclass(frozen=True, slots=True)
class FreezeRecord:
    frozen_artifact: FrozenArtifact
    candidate_hash: ContentHash
    review_id: str
    frozen_at: datetime


@dataclass(frozen=True, slots=True)
class BaselineRecord:
    baseline_id: BaselineId
    frozen_artifact_id: FrozenArtifactId
    lineage_id: LineageId


def freeze_candidate(
    *,
    candidate_id: CandidateId,
    candidate_hash: ContentHash,
    frozen_artifact_id: FrozenArtifactId,
    review: ReviewRecord,
    frozen_at: datetime,
) -> FreezeRecord:
    if not review.freeze_eligible:
        raise PermissionError("candidate is not freeze-eligible")
    if frozen_at.tzinfo is None:
        raise ValueError("freeze timestamp must be timezone-aware")
    return FreezeRecord(
        frozen_artifact=FrozenArtifact(frozen_artifact_id, candidate_id),
        candidate_hash=candidate_hash,
        review_id=review.review_id,
        frozen_at=frozen_at,
    )


def designate_baseline(
    baseline_id: BaselineId,
    lineage_id: LineageId,
    freeze: FreezeRecord,
) -> BaselineRecord:
    return BaselineRecord(baseline_id, freeze.frozen_artifact.id, lineage_id)


def approve_deployment(deployment_id: DeploymentId, frozen: FrozenArtifact) -> DeploymentRecord:
    return DeploymentRecord(deployment_id, frozen.id)
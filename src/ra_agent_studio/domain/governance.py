from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from .authority import DeploymentRecord, FrozenArtifact
from .candidate import CandidateRecord
from .identity import BaselineId, ContentHash, DeploymentId, FrozenArtifactId, LineageId
from .review import ReviewRecord


@dataclass(frozen=True, slots=True)
class FreezeRecord:
    frozen_artifact: FrozenArtifact
    candidate_hash: ContentHash
    review_id: str
    lineage_id: LineageId
    predecessor_baseline_id: BaselineId | None
    authority_grant_id: str
    frozen_by_principal_id: str
    frozen_at: datetime


@dataclass(frozen=True, slots=True)
class BaselineRecord:
    baseline_id: BaselineId
    frozen_artifact_id: FrozenArtifactId
    lineage_id: LineageId
    predecessor_baseline_id: BaselineId | None
    authority_grant_id: str
    promoted_by_principal_id: str
    promoted_at: datetime


def freeze_candidate(
    *,
    candidate: CandidateRecord,
    frozen_artifact_id: FrozenArtifactId,
    review: ReviewRecord,
    authority_grant_id: str,
    frozen_by_principal_id: str,
    frozen_at: datetime,
) -> FreezeRecord:
    if not review.freeze_eligible:
        raise PermissionError("candidate is not freeze-eligible")
    if review.subject_candidate_id != candidate.candidate_id:
        raise PermissionError("review is not bound to this exact candidate")
    if review.subject_hash != candidate.candidate_hash:
        raise PermissionError("review hash does not match exact candidate bytes")
    if review.workspace_id != candidate.workspace_id:
        raise PermissionError("review workspace does not match candidate workspace")
    if frozen_at.tzinfo is None:
        raise ValueError("freeze timestamp must be timezone-aware")
    return FreezeRecord(
        frozen_artifact=FrozenArtifact(frozen_artifact_id, candidate.candidate_id),
        candidate_hash=candidate.candidate_hash,
        review_id=review.review_id,
        lineage_id=candidate.lineage_id,
        predecessor_baseline_id=candidate.predecessor_baseline_id,
        authority_grant_id=authority_grant_id,
        frozen_by_principal_id=frozen_by_principal_id,
        frozen_at=frozen_at,
    )


def designate_baseline(
    *,
    baseline_id: BaselineId,
    lineage_id: LineageId,
    freeze: FreezeRecord,
    current_baseline: BaselineRecord | None,
    expected_predecessor_baseline_id: BaselineId | None,
    authority_grant_id: str,
    promoted_by_principal_id: str,
    promoted_at: datetime,
) -> BaselineRecord:
    if freeze.lineage_id != lineage_id:
        raise PermissionError("freeze lineage does not match promotion lineage")
    actual_predecessor = current_baseline.baseline_id if current_baseline else None
    if actual_predecessor != expected_predecessor_baseline_id:
        raise PermissionError("baseline predecessor changed; promotion is stale")
    if freeze.predecessor_baseline_id != expected_predecessor_baseline_id:
        raise PermissionError("candidate was not built from the current predecessor baseline")
    if promoted_at.tzinfo is None:
        raise ValueError("promotion timestamp must be timezone-aware")
    return BaselineRecord(
        baseline_id=baseline_id,
        frozen_artifact_id=freeze.frozen_artifact.id,
        lineage_id=lineage_id,
        predecessor_baseline_id=expected_predecessor_baseline_id,
        authority_grant_id=authority_grant_id,
        promoted_by_principal_id=promoted_by_principal_id,
        promoted_at=promoted_at,
    )


def approve_deployment(
    *,
    deployment_id: DeploymentId,
    freeze: FreezeRecord,
    current_baseline: BaselineRecord,
    authority_grant_id: str,
    activated_by_principal_id: str,
    activated_at: datetime,
) -> DeploymentRecord:
    if current_baseline.frozen_artifact_id != freeze.frozen_artifact.id:
        raise PermissionError("artifact is not the activation-time current baseline")
    if current_baseline.lineage_id != freeze.lineage_id:
        raise PermissionError("deployment lineage mismatch")
    if activated_at.tzinfo is None:
        raise ValueError("deployment activation timestamp must be timezone-aware")
    return DeploymentRecord(
        id=deployment_id,
        artifact_id=freeze.frozen_artifact.id,
        lineage_id=freeze.lineage_id,
        baseline_id=current_baseline.baseline_id,
        authority_grant_id=authority_grant_id,
        activated_by_principal_id=activated_by_principal_id,
        activated_at=activated_at,
    )

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from .identity import CandidateId, DeploymentId, FrozenArtifactId, LineageId, BaselineId


class AuthorityAction(StrEnum):
    REVIEW = "review"
    FREEZE = "freeze"
    PROMOTE = "promote"
    DEPLOY = "deploy"
    BUILD = "build"


@dataclass(frozen=True, slots=True)
class Candidate:
    id: CandidateId
    approved: bool = False


@dataclass(frozen=True, slots=True)
class FrozenArtifact:
    id: FrozenArtifactId
    source_candidate_id: CandidateId


@dataclass(frozen=True, slots=True)
class DeploymentRecord:
    id: DeploymentId
    artifact_id: FrozenArtifactId
    lineage_id: LineageId
    baseline_id: BaselineId
    authority_grant_id: str
    activated_by_principal_id: str
    activated_at: datetime

    def __post_init__(self) -> None:
        if self.activated_at.tzinfo is None:
            raise ValueError("deployment activation timestamp must be timezone-aware")


def require_deployable(artifact: object) -> FrozenArtifact:
    if not isinstance(artifact, FrozenArtifact):
        raise PermissionError("only FrozenArtifact may enter the deployment path")
    return artifact

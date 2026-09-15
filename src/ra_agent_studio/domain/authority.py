from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from .identity import CandidateId, DeploymentId, FrozenArtifactId


class AuthorityAction(StrEnum):
    REVIEW = "review"
    FREEZE = "freeze"
    PROMOTE = "promote"
    DEPLOY = "deploy"


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


def require_deployable(artifact: object) -> FrozenArtifact:
    """Deployment may only begin from an exact FrozenArtifact.

    Review success and candidate approval do not grant deployment authority.
    """
    if not isinstance(artifact, FrozenArtifact):
        raise PermissionError("only FrozenArtifact may enter the deployment path")
    return artifact

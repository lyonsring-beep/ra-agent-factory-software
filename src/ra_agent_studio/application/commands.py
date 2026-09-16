from __future__ import annotations

from dataclasses import dataclass

from ra_agent_studio.domain.identity import CandidateId, FrozenArtifactId
from ra_agent_studio.domain.state import CandidateState


@dataclass(frozen=True, slots=True)
class TransitionCandidateCommand:
    actor_id: str
    candidate_id: CandidateId
    target_state: CandidateState
    frozen_artifact_id: FrozenArtifactId | None = None

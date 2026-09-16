from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from .identity import ContentHash


@dataclass(frozen=True, slots=True)
class BuildEvidence:
    evidence_id: str
    composition_id: str
    composition_hash: ContentHash
    artifact_hash: ContentHash
    created_at: datetime
    reproducible: bool
    runtime_identity: str

    def __post_init__(self) -> None:
        if self.created_at.tzinfo is None:
            raise ValueError("evidence timestamp must be timezone-aware")
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from .identity import ContentHash, ModuleId, RevisionId


class ModuleRevisionState(StrEnum):
    DRAFT = "draft"
    CANDIDATE = "candidate"
    APPROVED = "approved"
    FROZEN = "frozen"


@dataclass(frozen=True, slots=True)
class ModuleRevision:
    module_id: ModuleId
    revision_id: RevisionId
    content_hash: ContentHash
    name: str
    content: str
    state: ModuleRevisionState = ModuleRevisionState.DRAFT
    predecessor_revision_id: RevisionId | None = None

    @classmethod
    def create(
        cls,
        module_id: ModuleId,
        revision_id: RevisionId,
        *,
        name: str,
        content: str,
        predecessor_revision_id: RevisionId | None = None,
    ) -> "ModuleRevision":
        return cls(
            module_id=module_id,
            revision_id=revision_id,
            content_hash=ContentHash.from_bytes(content.encode("utf-8")),
            name=name,
            content=content,
            predecessor_revision_id=predecessor_revision_id,
        )
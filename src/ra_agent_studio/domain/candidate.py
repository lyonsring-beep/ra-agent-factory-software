from __future__ import annotations

from dataclasses import dataclass

from .identity import BaselineId, CandidateId, ContentHash, LineageId


@dataclass(frozen=True, slots=True)
class CandidateRecord:
    candidate_id: CandidateId
    candidate_hash: ContentHash
    composition_id: str
    composition_hash: ContentHash
    factory_evidence_id: str
    factory_runtime_commit: str
    factory_candidate_sha256: str
    author_principal_id: str
    contributor_principal_ids: frozenset[str]
    workspace_id: str
    lineage_id: LineageId
    predecessor_baseline_id: BaselineId | None
    contributor_workspace_ids: frozenset[str] = frozenset()
    artifact_blob_hash: ContentHash | None = None
    logical_payload_identity: ContentHash | None = None
    manifest_identity: ContentHash | None = None
    factory_candidate_revision_id: str = ""

    def __post_init__(self) -> None:
        if self.author_principal_id not in self.contributor_principal_ids:
            object.__setattr__(
                self, "contributor_principal_ids",
                frozenset(set(self.contributor_principal_ids) | {self.author_principal_id}),
            )
        if not self.contributor_workspace_ids:
            object.__setattr__(self, "contributor_workspace_ids", frozenset({self.workspace_id}))

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import json

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
    author_principal_id: str = "system"
    state: ModuleRevisionState = ModuleRevisionState.DRAFT
    predecessor_revision_id: RevisionId | None = None
    provided_capabilities: tuple[str, ...] = ()
    required_capabilities: tuple[str, ...] = ()
    required_module_ids: tuple[ModuleId, ...] = ()
    incompatible_module_ids: tuple[ModuleId, ...] = ()
    identity_domain: str = ""
    config_json: str = "{}"
    config_hash: ContentHash | None = None

    @classmethod
    def create(
        cls,
        module_id: ModuleId,
        revision_id: RevisionId,
        *,
        name: str,
        content: str,
        author_principal_id: str = "system",
        predecessor_revision_id: RevisionId | None = None,
        provided_capabilities: tuple[str, ...] = (),
        required_capabilities: tuple[str, ...] = (),
        required_module_ids: tuple[ModuleId, ...] = (),
        incompatible_module_ids: tuple[ModuleId, ...] = (),
        identity_domain: str = "",
        config_json: str = "{}",
    ) -> "ModuleRevision":
        parsed_config = json.loads(config_json)
        canonical_config = json.dumps(parsed_config, sort_keys=True, separators=(",", ":"))
        canonical_payload = json.dumps(
            {
                "content": content,
                "provided_capabilities": sorted(set(provided_capabilities)),
                "required_capabilities": sorted(set(required_capabilities)),
                "required_module_ids": sorted(item.value for item in required_module_ids),
                "incompatible_module_ids": sorted(item.value for item in incompatible_module_ids),
                "identity_domain": identity_domain,
                "config": json.loads(canonical_config),
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return cls(
            module_id=module_id,
            revision_id=revision_id,
            content_hash=ContentHash.from_bytes(canonical_payload),
            name=name,
            content=content,
            author_principal_id=author_principal_id,
            predecessor_revision_id=predecessor_revision_id,
            provided_capabilities=tuple(sorted(set(provided_capabilities))),
            required_capabilities=tuple(sorted(set(required_capabilities))),
            required_module_ids=required_module_ids,
            incompatible_module_ids=incompatible_module_ids,
            identity_domain=identity_domain,
            config_json=canonical_config,
            config_hash=ContentHash.from_bytes(canonical_config.encode("utf-8")),
        )

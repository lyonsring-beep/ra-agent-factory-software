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


class ModuleType(StrEnum):
    AGENT_SPECIFIC_EXTENSION_MODULE = "AGENT_SPECIFIC_EXTENSION_MODULE"
    SHARED_CAPABILITY_MODULE = "SHARED_CAPABILITY_MODULE"
    SHARED_CONFIGURATION_MODULE = "SHARED_CONFIGURATION_MODULE"
    FROZEN_SHARED_FOUNDATION_MODULE = "FROZEN_SHARED_FOUNDATION_MODULE"


class ModuleAuthorityClass(StrEnum):
    FACTORY_AGENT_SPECIFIC = "FACTORY_AGENT_SPECIFIC"
    SHARED_CHANGE_REVIEW_REQUIRED = "SHARED_CHANGE_REVIEW_REQUIRED"
    FROZEN_SHARED_FOUNDATION = "FROZEN_SHARED_FOUNDATION"


class ModuleEditability(StrEnum):
    AGENT_EDITABLE = "agent_editable"
    REVIEW_GATED = "review_gated"
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
    module_type: ModuleType = ModuleType.AGENT_SPECIFIC_EXTENSION_MODULE
    authority_class: ModuleAuthorityClass = ModuleAuthorityClass.FACTORY_AGENT_SPECIFIC
    editability: ModuleEditability = ModuleEditability.AGENT_EDITABLE
    agent_requirement_ref: str = ""
    agent_authority_boundary_ref: str = ""
    shared_change_authorization_ref: str = ""

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
        module_type: ModuleType = ModuleType.AGENT_SPECIFIC_EXTENSION_MODULE,
        authority_class: ModuleAuthorityClass = ModuleAuthorityClass.FACTORY_AGENT_SPECIFIC,
        editability: ModuleEditability = ModuleEditability.AGENT_EDITABLE,
        agent_requirement_ref: str = "",
        agent_authority_boundary_ref: str = "",
        shared_change_authorization_ref: str = "",
    ) -> "ModuleRevision":
        if module_type is ModuleType.AGENT_SPECIFIC_EXTENSION_MODULE:
            if authority_class is not ModuleAuthorityClass.FACTORY_AGENT_SPECIFIC:
                raise ValueError("agent-specific module must retain FACTORY_AGENT_SPECIFIC authority")
        else:
            if not shared_change_authorization_ref:
                raise PermissionError("SHARED_CHANGE_REQUIRED_STOP: non-agent-specific module change lacks authorization")
            if editability is ModuleEditability.AGENT_EDITABLE:
                raise PermissionError("shared/frozen modules cannot be agent-editable")
        if not agent_requirement_ref or not agent_authority_boundary_ref:
            raise ValueError("exact AgentRequirement and AgentAuthorityBoundary refs are required")

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
                "module_type": module_type.value,
                "authority_class": authority_class.value,
                "editability": editability.value,
                "agent_requirement_ref": agent_requirement_ref,
                "agent_authority_boundary_ref": agent_authority_boundary_ref,
                "shared_change_authorization_ref": shared_change_authorization_ref,
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
            module_type=module_type,
            authority_class=authority_class,
            editability=editability,
            agent_requirement_ref=agent_requirement_ref,
            agent_authority_boundary_ref=agent_authority_boundary_ref,
            shared_change_authorization_ref=shared_change_authorization_ref,
        )

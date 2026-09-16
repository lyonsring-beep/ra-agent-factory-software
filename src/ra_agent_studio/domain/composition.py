from __future__ import annotations

from dataclasses import dataclass

from .identity import ContentHash, ModuleId, RevisionId


@dataclass(frozen=True, slots=True)
class ModuleBinding:
    module_id: ModuleId
    revision_id: RevisionId
    content_hash: ContentHash


@dataclass(frozen=True, slots=True)
class CompatibilityIssue:
    code: str
    message: str


@dataclass(frozen=True, slots=True)
class RealizedAgentComposition:
    composition_id: str
    bindings: tuple[ModuleBinding, ...]
    composition_hash: ContentHash


def realize_composition(composition_id: str, bindings: tuple[ModuleBinding, ...]) -> RealizedAgentComposition:
    if not bindings:
        raise ValueError("composition requires at least one exact module binding")
    seen: set[str] = set()
    for binding in bindings:
        if binding.module_id.value in seen:
            raise ValueError(f"duplicate module binding: {binding.module_id.value}")
        seen.add(binding.module_id.value)
    canonical = "\n".join(
        f"{b.module_id.value}:{b.revision_id.value}:{b.content_hash.value}" for b in bindings
    ).encode("utf-8")
    return RealizedAgentComposition(
        composition_id=composition_id,
        bindings=bindings,
        composition_hash=ContentHash.from_bytes(canonical),
    )
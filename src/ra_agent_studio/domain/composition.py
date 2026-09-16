from __future__ import annotations

from dataclasses import dataclass

from .identity import ContentHash, ModuleId, RevisionId


@dataclass(frozen=True, slots=True)
class ModuleBinding:
    module_id: ModuleId
    revision_id: RevisionId
    content_hash: ContentHash
    provided_capabilities: tuple[str, ...] = ()
    required_capabilities: tuple[str, ...] = ()
    required_module_ids: tuple[ModuleId, ...] = ()
    incompatible_module_ids: tuple[ModuleId, ...] = ()
    identity_domain: str = ""
    config_hash: ContentHash | None = None


@dataclass(frozen=True, slots=True)
class CompatibilityIssue:
    code: str
    message: str


@dataclass(frozen=True, slots=True)
class RealizedAgentComposition:
    composition_id: str
    bindings: tuple[ModuleBinding, ...]
    composition_hash: ContentHash


def assess_compatibility(bindings: tuple[ModuleBinding, ...]) -> tuple[CompatibilityIssue, ...]:
    issues: list[CompatibilityIssue] = []
    by_module: dict[str, ModuleBinding] = {}
    for binding in bindings:
        if binding.module_id.value in by_module:
            issues.append(CompatibilityIssue("duplicate_module", f"duplicate module binding: {binding.module_id.value}"))
        by_module[binding.module_id.value] = binding

    all_capabilities = {cap for binding in bindings for cap in binding.provided_capabilities}
    for binding in bindings:
        missing_caps = sorted(set(binding.required_capabilities) - all_capabilities)
        if missing_caps:
            issues.append(
                CompatibilityIssue(
                    "missing_capability",
                    f"{binding.module_id.value} requires capabilities: {', '.join(missing_caps)}",
                )
            )
        for required in binding.required_module_ids:
            if required.value not in by_module:
                issues.append(
                    CompatibilityIssue(
                        "missing_required_module",
                        f"{binding.module_id.value} requires module {required.value}",
                    )
                )
        for incompatible in binding.incompatible_module_ids:
            if incompatible.value in by_module:
                issues.append(
                    CompatibilityIssue(
                        "incompatible_module",
                        f"{binding.module_id.value} is incompatible with {incompatible.value}",
                    )
                )
        if binding.config_hash is None:
            issues.append(CompatibilityIssue("missing_config_identity", f"{binding.module_id.value} has no exact config hash"))

    identity_domains: dict[str, str] = {}
    for binding in bindings:
        if not binding.identity_domain:
            continue
        prior = identity_domains.get(binding.identity_domain)
        if prior is not None and prior != binding.module_id.value:
            issues.append(
                CompatibilityIssue(
                    "identity_domain_conflict",
                    f"identity domain {binding.identity_domain} is claimed by both {prior} and {binding.module_id.value}",
                )
            )
        identity_domains[binding.identity_domain] = binding.module_id.value

    graph = {
        binding.module_id.value: [dep.value for dep in binding.required_module_ids if dep.value in by_module]
        for binding in bindings
    }
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(node: str) -> None:
        if node in visiting:
            issues.append(CompatibilityIssue("dependency_cycle", f"dependency cycle detected at {node}"))
            return
        if node in visited:
            return
        visiting.add(node)
        for dep in graph.get(node, []):
            visit(dep)
        visiting.remove(node)
        visited.add(node)

    for node in graph:
        visit(node)
    return tuple(issues)


def realize_composition(composition_id: str, bindings: tuple[ModuleBinding, ...]) -> RealizedAgentComposition:
    if not bindings:
        raise ValueError("composition requires at least one exact module binding")
    issues = assess_compatibility(bindings)
    if issues:
        detail = "; ".join(f"{issue.code}: {issue.message}" for issue in issues)
        raise ValueError(f"composition compatibility failed: {detail}")
    canonical = "\n".join(
        ":".join(
            [
                b.module_id.value,
                b.revision_id.value,
                b.content_hash.value,
                b.config_hash.value if b.config_hash else "",
                ",".join(sorted(b.provided_capabilities)),
                ",".join(sorted(b.required_capabilities)),
                ",".join(sorted(x.value for x in b.required_module_ids)),
                b.identity_domain,
            ]
        )
        for b in sorted(bindings, key=lambda item: item.module_id.value)
    ).encode("utf-8")
    return RealizedAgentComposition(
        composition_id=composition_id,
        bindings=bindings,
        composition_hash=ContentHash.from_bytes(canonical),
    )

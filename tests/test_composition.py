import pytest

from ra_agent_studio.domain.composition import ModuleBinding, realize_composition
from ra_agent_studio.domain.identity import ContentHash, ModuleId, RevisionId


def binding(
    module: str,
    revision: str,
    text: bytes,
    *,
    provides=(),
    requires=(),
    required_modules=(),
    incompatible=(),
    identity_domain="",
) -> ModuleBinding:
    return ModuleBinding(
        ModuleId(module),
        RevisionId(revision),
        ContentHash.from_bytes(text),
        tuple(provides),
        tuple(requires),
        tuple(ModuleId(x) for x in required_modules),
        tuple(ModuleId(x) for x in incompatible),
        identity_domain,
        ContentHash.from_bytes(b"{}"),
    )


def test_composition_binds_exact_revisions_and_capabilities() -> None:
    result = realize_composition(
        "c1",
        (
            binding("source", "r1", b"one", provides=("evidence",)),
            binding("consumer", "r2", b"two", requires=("evidence",), required_modules=("source",)),
        ),
    )
    assert len(result.bindings) == 2
    assert len(result.composition_hash.value) == 64


def test_duplicate_module_binding_is_rejected() -> None:
    with pytest.raises(ValueError, match="duplicate_module"):
        realize_composition("c1", (binding("m1", "r1", b"one"), binding("m1", "r2", b"two")))


def test_missing_capability_is_rejected() -> None:
    with pytest.raises(ValueError, match="missing_capability"):
        realize_composition("c1", (binding("m1", "r1", b"one", requires=("missing",)),))


def test_incompatible_module_pair_is_rejected() -> None:
    with pytest.raises(ValueError, match="incompatible_module"):
        realize_composition(
            "c1",
            (binding("m1", "r1", b"one", incompatible=("m2",)), binding("m2", "r2", b"two")),
        )


def test_dependency_cycle_is_rejected() -> None:
    with pytest.raises(ValueError, match="dependency_cycle"):
        realize_composition(
            "c1",
            (
                binding("m1", "r1", b"one", required_modules=("m2",)),
                binding("m2", "r2", b"two", required_modules=("m1",)),
            ),
        )

import pytest

from ra_agent_studio.domain.composition import ModuleBinding, realize_composition
from ra_agent_studio.domain.identity import ContentHash, ModuleId, RevisionId


def binding(module: str, revision: str, text: bytes) -> ModuleBinding:
    return ModuleBinding(ModuleId(module), RevisionId(revision), ContentHash.from_bytes(text))


def test_composition_binds_exact_revisions() -> None:
    result = realize_composition("c1", (binding("m1", "r1", b"one"), binding("m2", "r2", b"two")))
    assert len(result.bindings) == 2
    assert len(result.composition_hash.value) == 64


def test_duplicate_module_binding_is_rejected() -> None:
    with pytest.raises(ValueError):
        realize_composition("c1", (binding("m1", "r1", b"one"), binding("m1", "r2", b"two")))
from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256


@dataclass(frozen=True, slots=True)
class ContentHash:
    value: str

    def __post_init__(self) -> None:
        if len(self.value) != 64:
            raise ValueError("content hash must be a 64-character SHA-256 hex digest")
        int(self.value, 16)

    @classmethod
    def from_bytes(cls, payload: bytes) -> "ContentHash":
        return cls(sha256(payload).hexdigest())


@dataclass(frozen=True, slots=True)
class ModuleId:
    value: str


@dataclass(frozen=True, slots=True)
class RevisionId:
    value: str


@dataclass(frozen=True, slots=True)
class BaselineId:
    value: str


@dataclass(frozen=True, slots=True)
class LineageId:
    value: str


@dataclass(frozen=True, slots=True)
class CandidateId:
    value: str


@dataclass(frozen=True, slots=True)
class FrozenArtifactId:
    value: str


@dataclass(frozen=True, slots=True)
class DeploymentId:
    value: str

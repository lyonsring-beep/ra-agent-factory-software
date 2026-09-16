from __future__ import annotations

from typing import Protocol

from ra_agent_studio.domain.audit import AuditEvent
from ra_agent_studio.domain.identity import CandidateId
from ra_agent_studio.domain.state import CandidateStateRecord


class CandidateRepository(Protocol):
    def get(self, candidate_id: CandidateId) -> CandidateStateRecord: ...
    def save(self, record: CandidateStateRecord) -> None: ...


class AuditRepository(Protocol):
    def append(self, event: AuditEvent) -> None: ...


class UnitOfWork(Protocol):
    candidates: CandidateRepository
    audit: AuditRepository

    def __enter__(self) -> "UnitOfWork": ...
    def __exit__(self, exc_type, exc, tb) -> None: ...
    def commit(self) -> None: ...
    def rollback(self) -> None: ...

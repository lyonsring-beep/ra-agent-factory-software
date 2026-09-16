from __future__ import annotations

from contextlib import AbstractContextManager
from dataclasses import replace

from ra_agent_studio.domain.audit import AuditEvent
from ra_agent_studio.domain.identity import RevisionId
from ra_agent_studio.domain.module import ModuleRevision


class InMemoryModuleRepository:
    def __init__(self) -> None:
        self._items: dict[str, ModuleRevision] = {}

    def add(self, revision: ModuleRevision) -> None:
        key = revision.revision_id.value
        if key in self._items:
            raise ValueError(f"revision already exists: {key}")
        self._items[key] = revision

    def get(self, revision_id: RevisionId) -> ModuleRevision:
        try:
            return self._items[revision_id.value]
        except KeyError as exc:
            raise KeyError(f"unknown revision: {revision_id.value}") from exc

    def list(self) -> tuple[ModuleRevision, ...]:
        return tuple(self._items.values())

    def replace(self, revision: ModuleRevision) -> None:
        if revision.revision_id.value not in self._items:
            raise KeyError(revision.revision_id.value)
        self._items[revision.revision_id.value] = revision


class InMemoryAuditRepository:
    def __init__(self) -> None:
        self.events: list[AuditEvent] = []

    def append(self, event: AuditEvent) -> None:
        self.events.append(event)


class InMemoryUnitOfWork(AbstractContextManager["InMemoryUnitOfWork"]):
    def __init__(self) -> None:
        self.committed = False
        self.rolled_back = False

    def __enter__(self) -> "InMemoryUnitOfWork":
        self.committed = False
        self.rolled_back = False
        return self

    def commit(self) -> None:
        self.committed = True

    def rollback(self) -> None:
        self.rolled_back = True

    def __exit__(self, exc_type, exc, tb) -> bool:
        if exc is not None:
            self.rollback()
        elif not self.committed:
            self.rollback()
        return False
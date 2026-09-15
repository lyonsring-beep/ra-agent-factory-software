from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Mapping

from .authority import AuthorityAction


@dataclass(frozen=True, slots=True)
class AuditEvent:
    event_id: str
    occurred_at: datetime
    actor_id: str
    action: AuthorityAction
    subject_type: str
    subject_id: str
    metadata: Mapping[str, str]

    def __post_init__(self) -> None:
        if self.occurred_at.tzinfo is None:
            raise ValueError("audit event timestamp must be timezone-aware")

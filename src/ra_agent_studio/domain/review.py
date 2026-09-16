from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class ReviewVerdict(StrEnum):
    PASS = "pass"
    FAIL = "fail"


@dataclass(frozen=True, slots=True)
class ReviewBlocker:
    blocker_id: str
    description: str
    closed: bool = False


@dataclass(frozen=True, slots=True)
class ReviewRecord:
    review_id: str
    subject_id: str
    reviewer_id: str
    verdict: ReviewVerdict
    blockers: tuple[ReviewBlocker, ...] = ()

    @property
    def freeze_eligible(self) -> bool:
        return self.verdict is ReviewVerdict.PASS and all(b.closed for b in self.blockers)


def require_independent_reviewer(author_id: str, reviewer_id: str) -> None:
    if author_id == reviewer_id:
        raise PermissionError("reviewer must be independent from author")
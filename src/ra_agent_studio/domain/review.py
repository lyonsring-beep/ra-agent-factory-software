from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from .auth import AuthorityGrant
from .candidate import CandidateRecord
from .identity import CandidateId, ContentHash


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
    subject_candidate_id: CandidateId
    subject_hash: ContentHash
    reviewer_principal_id: str
    authority_grant_id: str
    review_method: str
    scope: str
    workspace_id: str
    verdict: ReviewVerdict
    blockers: tuple[ReviewBlocker, ...] = ()

    @property
    def freeze_eligible(self) -> bool:
        return self.verdict is ReviewVerdict.PASS and all(b.closed for b in self.blockers)


def create_review_record(
    *,
    review_id: str,
    candidate: CandidateRecord,
    reviewer_principal_id: str,
    authority_grant: AuthorityGrant,
    review_method: str,
    verdict: ReviewVerdict,
    blockers: tuple[ReviewBlocker, ...] = (),
) -> ReviewRecord:
    if authority_grant.principal_id != reviewer_principal_id:
        raise PermissionError("review grant is not owned by reviewer principal")
    if authority_grant.workspace_id != candidate.workspace_id:
        raise PermissionError("review grant workspace does not match candidate workspace")
    if review_method not in authority_grant.review_methods:
        raise PermissionError("review method is not authorized by the review grant")
    contributors = set(candidate.contributor_principal_ids)
    if reviewer_principal_id in contributors:
        raise PermissionError("reviewer contributed to the candidate and is not independent")
    if not contributors.issubset(authority_grant.independent_of_principals):
        raise PermissionError("review grant does not attest contribution independence")
    return ReviewRecord(
        review_id=review_id,
        subject_candidate_id=candidate.candidate_id,
        subject_hash=candidate.candidate_hash,
        reviewer_principal_id=reviewer_principal_id,
        authority_grant_id=authority_grant.grant_id,
        review_method=review_method,
        scope="exact_candidate",
        workspace_id=candidate.workspace_id,
        verdict=verdict,
        blockers=blockers,
    )

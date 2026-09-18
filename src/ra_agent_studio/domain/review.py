from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from .auth import AuthorityGrant, Principal
from .candidate import CandidateRecord
from .identity import CandidateId, ContentHash


class ReviewVerdict(StrEnum):
    PASS = "pass"
    FAIL = "fail"
    INCONCLUSIVE = "inconclusive"


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
    reviewer_workspace_id: str
    authority_grant_id: str
    authority_source: str
    review_method: str
    scope: str
    target_workspace_id: str
    verdict: ReviewVerdict
    blockers: tuple[ReviewBlocker, ...] = ()

    @property
    def workspace_id(self) -> str:
        return self.target_workspace_id

    @property
    def freeze_eligible(self) -> bool:
        return self.verdict is ReviewVerdict.PASS and all(b.closed for b in self.blockers)


def create_review_record(
    *,
    review_id: str,
    candidate: CandidateRecord,
    reviewer: Principal,
    authority_grant: AuthorityGrant,
    review_method: str,
    verdict: ReviewVerdict,
    blockers: tuple[ReviewBlocker, ...] = (),
) -> ReviewRecord:
    if authority_grant.principal_id != reviewer.principal_id:
        raise PermissionError("review grant is not owned by reviewer principal")
    if authority_grant.workspace_id != candidate.workspace_id:
        raise PermissionError("review grant target workspace does not match candidate workspace")
    if review_method not in authority_grant.review_methods:
        raise PermissionError("review method is not authorized by the review grant")
    contributors = set(candidate.contributor_principal_ids)
    contribution_workspaces = set(candidate.contributor_workspace_ids)
    if reviewer.principal_id in contributors:
        raise PermissionError("reviewer contributed to the candidate and is not independent")
    if reviewer.workspace_id in contribution_workspaces:
        raise PermissionError("reviewer workspace contributed to the exact candidate and is not independent")
    if not contributors.issubset(authority_grant.independent_of_principals):
        raise PermissionError("review grant does not attest principal contribution independence")
    if not contribution_workspaces.issubset(authority_grant.independent_of_workspaces):
        raise PermissionError("review grant does not attest workspace contribution independence")
    if not authority_grant.authority_source or not authority_grant.target_scope:
        raise PermissionError("review grant lacks bounded authority source/target standing")
    return ReviewRecord(
        review_id=review_id,
        subject_candidate_id=candidate.candidate_id,
        subject_hash=candidate.candidate_hash,
        reviewer_principal_id=reviewer.principal_id,
        reviewer_workspace_id=reviewer.workspace_id,
        authority_grant_id=authority_grant.grant_id,
        authority_source=authority_grant.authority_source,
        review_method=review_method,
        scope="exact_candidate",
        target_workspace_id=candidate.workspace_id,
        verdict=verdict,
        blockers=blockers,
    )

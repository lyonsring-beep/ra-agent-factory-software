from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from ra_agent_studio.domain.audit import AuditEvent
from ra_agent_studio.domain.authority import AuthorityAction
from ra_agent_studio.domain.state import CandidateState, transition_candidate

from .commands import TransitionCandidateCommand
from .ports import UnitOfWork


def _action_for_target(target: CandidateState) -> AuthorityAction:
    if target in {CandidateState.REVIEW_PASSED, CandidateState.REVIEW_FAILED}:
        return AuthorityAction.REVIEW
    if target is CandidateState.FROZEN:
        return AuthorityAction.FREEZE
    return AuthorityAction.PROMOTE


def transition_candidate_authoritatively(
    command: TransitionCandidateCommand,
    uow: UnitOfWork,
):
    with uow:
        current = uow.candidates.get(command.candidate_id)
        updated = transition_candidate(
            current,
            command.target_state,
            frozen_artifact_id=command.frozen_artifact_id,
        )
        uow.candidates.save(updated)
        uow.audit.append(
            AuditEvent(
                event_id=str(uuid4()),
                occurred_at=datetime.now(UTC),
                actor_id=command.actor_id,
                action=_action_for_target(command.target_state),
                subject_type="candidate",
                subject_id=command.candidate_id.value,
                metadata={
                    "from_state": current.state.value,
                    "to_state": command.target_state.value,
                },
            )
        )
        uow.commit()
        return updated

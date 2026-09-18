from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType


@dataclass(frozen=True, slots=True)
class ApplicationOperationDescriptor:
    descriptor_id: str
    key: str
    intent: str
    authority_changing: bool = True


# Exact Frozen Factory v1.11 governance descriptor keys/intents. Studio does not invent
# alternate authority-bearing operation names; UI/API/CLI project this closed catalog.
_GOVERNANCE = {
    "baseline-lock":"BASELINE_LOCKED",
    "design-candidate-produced":"DESIGN_CANDIDATE_PRODUCED",
    "submit-design-review":"DESIGN_REVIEW_SUBMITTED",
    "authorize-design-repair":"DESIGN_REPAIR_AUTHORIZED",
    "design-candidate-revised":"DESIGN_CANDIDATE_REVISED",
    "authorize-design-evidence-remediation":"DESIGN_EVIDENCE_REMEDIATION_AUTHORIZED",
    "design-evidence-remediated":"DESIGN_EVIDENCE_REMEDIATED",
    "shared-review-required":"SHARED_REVIEW_REQUIRED",
    "shared-baseline-frozen":"SHARED_BASELINE_FROZEN",
    "design-review-pass":"DESIGN_REVIEW_PASS",
    "design-frozen":"DESIGN_FROZEN",
    "implementation-handoff-completed":"IMPLEMENTATION_HANDOFF_COMPLETED",
    "coding-begins":"CODING_BEGINS",
    "implementation-candidate-ready":"IMPLEMENTATION_CANDIDATE_READY",
    "submit-implementation-review":"IMPLEMENTATION_REVIEW_SUBMITTED",
    "authorize-implementation-repair":"IMPLEMENTATION_REPAIR_AUTHORIZED",
    "implementation-candidate-revised":"IMPLEMENTATION_CANDIDATE_REVISED",
    "design-reopen-required":"DESIGN_REOPEN_REQUIRED",
    "design-reopen-completed":"DESIGN_REOPEN_COMPLETED",
    "authorize-implementation-evidence-remediation":"IMPLEMENTATION_EVIDENCE_REMEDIATION_AUTHORIZED",
    "implementation-evidence-remediated":"IMPLEMENTATION_EVIDENCE_REMEDIATED",
    "implementation-review-pass":"IMPLEMENTATION_REVIEW_PASS",
    "implementation-frozen-accepted":"IMPLEMENTATION_FROZEN_ACCEPTED",
    "stale-baseline-detected":"STALE_BASELINE_DETECTED",
    "stale-reconciled-no-design-change":"STALE_RECONCILED_NO_DESIGN_CHANGE",
    "stale-reconciliation-invalidates-design":"STALE_RECONCILIATION_INVALIDATES_DESIGN",
    "canonical-closure-complete":"CANONICAL_CLOSURE_COMPLETE",
}
_FACTORY = {
    "requirement-submit":"REQUIREMENT_SUBMIT",
    "module-revision-create":"MODULE_REVISION_CREATE",
    "composition-realize":"COMPOSITION_REALIZE",
    "candidate-build":"CANDIDATE_BUILD",
    "candidate-verify":"CANDIDATE_VERIFY",
    "verification-plan-constitute":"VERIFICATION_PLAN_CONSTITUTE",
    "verification-plan-run":"VERIFICATION_PLAN_RUN",
    "controlled-execution-profile-register":"CONTROLLED_EXECUTION_PROFILE_REGISTER",
    "controlled-execution-run":"CONTROLLED_EXECUTION_RUN",
    "regression-evidence-record":"REGRESSION_EVIDENCE_RECORD",
    "external-frozen-register":"EXTERNAL_FROZEN_REGISTER",
    "review-decision-ingest":"REVIEW_DECISION_INGEST",
    "exact-freeze":"EXACT_FREEZE",
    "canonical-promote":"CANONICAL_PROMOTE",
    "prerequisite-design-authoring-record":"PREREQUISITE_DESIGN_AUTHORING_RECORD",
    "prerequisite-implementation-authoring-record":"PREREQUISITE_IMPLEMENTATION_AUTHORING_RECORD",
    "prerequisite-design-freeze-record":"PREREQUISITE_DESIGN_FREEZE_RECORD",
    "prerequisite-shared-baseline-freeze-record":"PREREQUISITE_SHARED_BASELINE_FREEZE_RECORD",
    "prerequisite-design-reopen-chain-record":"PREREQUISITE_DESIGN_REOPEN_CHAIN_RECORD",
    "prerequisite-baseline-reconciliation-record":"PREREQUISITE_BASELINE_RECONCILIATION_RECORD",
}

GOVERNANCE_OPERATION_MAP = MappingProxyType({
    k: ApplicationOperationDescriptor(f"op:governance:{k}", k, v) for k,v in _GOVERNANCE.items()
})
FACTORY_OPERATION_MAP = MappingProxyType({
    k: ApplicationOperationDescriptor(f"op:factory:{k}", k, v) for k,v in _FACTORY.items()
})
APPLICATION_OPERATION_CATALOG = MappingProxyType({
    **{x.descriptor_id:x for x in GOVERNANCE_OPERATION_MAP.values()},
    **{x.descriptor_id:x for x in FACTORY_OPERATION_MAP.values()},
})


def descriptor(descriptor_id: str) -> ApplicationOperationDescriptor:
    try:
        return APPLICATION_OPERATION_CATALOG[descriptor_id]
    except KeyError as exc:
        raise ValueError(f"UNKNOWN_OPERATION_DESCRIPTOR:{descriptor_id}") from exc

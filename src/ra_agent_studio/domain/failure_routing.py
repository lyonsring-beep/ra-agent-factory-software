from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from .production import ProductionEvent, ProductionState


class FailureClass(StrEnum):
    FC_1_DESIGN_DEFECT="FC-1_DESIGN_DEFECT"
    FC_2_LOCAL_IMPLEMENTATION_DEFECT="FC-2_LOCAL_IMPLEMENTATION_DEFECT"
    FC_3_SHARED_ARCHITECTURE_REQUIREMENT="FC-3_SHARED_ARCHITECTURE_REQUIREMENT"
    FC_4_UPSTREAM_PRECONDITION_EVIDENCE="FC-4_UPSTREAM_PRECONDITION_EVIDENCE"
    FC_5_TRACEABILITY_ONLY="FC-5_TRACEABILITY_ONLY"
    FC_6_EVIDENCE_ACCESS_TRANSPORT="FC-6_EVIDENCE_ACCESS_TRANSPORT"
    FC_7_TEST_ENVIRONMENT_TOOLING="FC-7_TEST_ENVIRONMENT_TOOLING"
    FC_8_PACKAGE_INTEGRITY="FC-8_PACKAGE_INTEGRITY"


class ProductionStage(StrEnum):
    DESIGN="DESIGN"
    IMPLEMENTATION="IMPLEMENTATION"


class CandidateMutationStanding(StrEnum):
    UNCHANGED="UNCHANGED"
    CANDIDATE_MUTATING="CANDIDATE_MUTATING"
    CONTAINER_ONLY="CONTAINER_ONLY"
    LOGICAL_PAYLOAD_CHANGING="LOGICAL_PAYLOAD_CHANGING"


@dataclass(frozen=True, slots=True)
class FailureRoute:
    failure_class: FailureClass
    stage: ProductionStage
    mutation_standing: CandidateMutationStanding
    routed_state: ProductionState
    authorization_event: ProductionEvent
    return_event: ProductionEvent
    candidate_bytes_may_change: bool
    route_basis: str


def route_failure(
    failure_class: FailureClass,
    *,
    stage: ProductionStage,
    mutation_standing: CandidateMutationStanding,
) -> FailureRoute:
    if stage is ProductionStage.DESIGN:
        if failure_class is FailureClass.FC_2_LOCAL_IMPLEMENTATION_DEFECT:
            raise ValueError("FC-2 is not applicable before implementation exists")
        if failure_class is FailureClass.FC_3_SHARED_ARCHITECTURE_REQUIREMENT:
            return FailureRoute(
                failure_class,stage,mutation_standing,ProductionState.PR_13_SHARED_REVIEW_REQUIRED,
                ProductionEvent.SHARED_REVIEW_REQUIRED,ProductionEvent.SHARED_BASELINE_FROZEN,False,
                "SHARED_REVIEW_REQUIRED",
            )
        if failure_class is FailureClass.FC_1_DESIGN_DEFECT or (
            failure_class is FailureClass.FC_5_TRACEABILITY_ONLY and mutation_standing is CandidateMutationStanding.CANDIDATE_MUTATING
        ) or (
            failure_class is FailureClass.FC_8_PACKAGE_INTEGRITY and mutation_standing is CandidateMutationStanding.LOGICAL_PAYLOAD_CHANGING
        ):
            return FailureRoute(
                failure_class,stage,mutation_standing,ProductionState.PR_04_DESIGN_REPAIR_AUTHORIZED,
                ProductionEvent.DESIGN_REPAIR_AUTHORIZED,ProductionEvent.DESIGN_CANDIDATE_REVISED,True,
                "DESIGN_REPAIR",
            )
        if failure_class in {
            FailureClass.FC_4_UPSTREAM_PRECONDITION_EVIDENCE,
            FailureClass.FC_6_EVIDENCE_ACCESS_TRANSPORT,
            FailureClass.FC_7_TEST_ENVIRONMENT_TOOLING,
        } or (failure_class is FailureClass.FC_5_TRACEABILITY_ONLY and mutation_standing is CandidateMutationStanding.UNCHANGED) or (
            failure_class is FailureClass.FC_8_PACKAGE_INTEGRITY and mutation_standing in {CandidateMutationStanding.UNCHANGED,CandidateMutationStanding.CONTAINER_ONLY}
        ):
            return FailureRoute(
                failure_class,stage,mutation_standing,ProductionState.PR_04E_DESIGN_EVIDENCE_REMEDIATION_REQUIRED,
                ProductionEvent.DESIGN_EVIDENCE_REMEDIATION_AUTHORIZED,ProductionEvent.DESIGN_EVIDENCE_REMEDIATED,False,
                "DESIGN_EVIDENCE_REMEDIATION",
            )
        raise ValueError("failure class/mutation standing is not a legal design-stage Frozen route")

    if failure_class is FailureClass.FC_1_DESIGN_DEFECT:
        return FailureRoute(
            failure_class,stage,mutation_standing,ProductionState.PR_12_DESIGN_REOPEN_REQUIRED,
            ProductionEvent.DESIGN_REOPEN_REQUIRED,ProductionEvent.DESIGN_REOPEN_COMPLETED,True,
            "DESIGN_REOPEN_REQUIRED",
        )
    if failure_class is FailureClass.FC_2_LOCAL_IMPLEMENTATION_DEFECT or (
        failure_class is FailureClass.FC_5_TRACEABILITY_ONLY and mutation_standing is CandidateMutationStanding.CANDIDATE_MUTATING
    ) or (
        failure_class is FailureClass.FC_8_PACKAGE_INTEGRITY and mutation_standing is CandidateMutationStanding.LOGICAL_PAYLOAD_CHANGING
    ):
        return FailureRoute(
            failure_class,stage,mutation_standing,ProductionState.PR_11_IMPLEMENTATION_REPAIR_AUTHORIZED,
            ProductionEvent.IMPLEMENTATION_REPAIR_AUTHORIZED,ProductionEvent.IMPLEMENTATION_CANDIDATE_REVISED,True,
            "IMPLEMENTATION_REPAIR",
        )
    if failure_class is FailureClass.FC_3_SHARED_ARCHITECTURE_REQUIREMENT:
        return FailureRoute(
            failure_class,stage,mutation_standing,ProductionState.PR_13_SHARED_REVIEW_REQUIRED,
            ProductionEvent.SHARED_REVIEW_REQUIRED,ProductionEvent.SHARED_BASELINE_FROZEN,False,
            "SHARED_REVIEW_REQUIRED",
        )
    if failure_class in {
        FailureClass.FC_4_UPSTREAM_PRECONDITION_EVIDENCE,
        FailureClass.FC_6_EVIDENCE_ACCESS_TRANSPORT,
        FailureClass.FC_7_TEST_ENVIRONMENT_TOOLING,
    } or (failure_class is FailureClass.FC_5_TRACEABILITY_ONLY and mutation_standing is CandidateMutationStanding.UNCHANGED) or (
        failure_class is FailureClass.FC_8_PACKAGE_INTEGRITY and mutation_standing in {CandidateMutationStanding.UNCHANGED,CandidateMutationStanding.CONTAINER_ONLY}
    ):
        return FailureRoute(
            failure_class,stage,mutation_standing,ProductionState.PR_14_REVIEW_EVIDENCE_REMEDIATION_REQUIRED,
            ProductionEvent.IMPLEMENTATION_EVIDENCE_REMEDIATION_AUTHORIZED,ProductionEvent.IMPLEMENTATION_EVIDENCE_REMEDIATED,False,
            "IMPLEMENTATION_EVIDENCE_REMEDIATION",
        )
    raise ValueError("failure class/mutation standing is not a legal implementation-stage Frozen route")

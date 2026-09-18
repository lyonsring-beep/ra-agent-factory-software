# RA Agent Studio Implementation v1.02 — Targeted Repair Evidence Map

Status: INTERNAL CANDIDATE PREPARATION / EXTERNAL RE-REVIEW NOT YET PERFORMED

This document maps the authorized v1.01 external-review repair scope to concrete v1.02 implementation and regression surfaces. It does not assert external closure or software-freeze authorization.

## V101-B01 — same-target review independence / authority standing

Implemented:
- Server-owned principals and authority grants.
- Reviewer principal and reviewer workspace are bound to the review record.
- Exact candidate contributor principal/workspace provenance is materialized.
- Same-target reviewer principal or contributed workspace is rejected.
- Review method, authority source, target scope and grant standing are required.
- Immutable ReviewSubmission and review-admission records bind exact target/hash/method/authority/reviewer.

Evidence:
- `tests/test_repair_blockers.py`
- `tests/test_v102_remaining_blockers.py`

## V101-B02 — Frozen B08 governance / failure routing

Implemented:
- Exact Frozen PR-00 through PR-17 state/event relation.
- Main implementation path uses PR-08 → PR-09 → PR-10 → PR-15 → PR-16 → PR-17.
- Canonical FC-1…FC-8 failure taxonomy is explicit.
- Design-stage and implementation-stage routes distinguish design repair, local implementation repair, shared review, evidence remediation and design reopen.
- FAIL/INCONCLUSIVE require FailureClassification + AuthorizedReopenScope.
- PR-15 stale-baseline detection routes to PR-15R and requires reconciliation.
- Immutable production transitions, ContributionRecord-equivalent records, review submission/admission and failure-route records are persisted.

Evidence:
- `src/ra_agent_studio/domain/production.py`
- `src/ra_agent_studio/domain/failure_routing.py`
- `tests/test_v102_governance_conformance.py`
- `tests/test_v102_remaining_blockers.py`

## V101-B03 — B09 exact closure / promotion critical section

Implemented:
- Exact Factory-produced candidate bytes are content-addressed and re-read at freeze.
- Candidate closure binds container identity, logical-payload identity, manifest identity and Factory candidate revision.
- PASS creates exact B09ClosureEligibility with ReviewAcceptedTransportBasis-equivalent identity tuple.
- Freeze requires exact candidate/review eligibility.
- Freeze closure binds exact bytes/identities/custody workspace.
- One exclusive canonical promotion lock and fencing token is held continuously from exact freeze through canonical pointer update.
- Pointer update is expected-value + ExpectedConsistencyVersion guarded.
- Lock is released only after promotion and PR-17 transition.

Evidence:
- `src/ra_agent_studio/infra/sqlite.py`
- `src/ra_agent_studio/application/studio.py`
- `tests/test_v102_governance_conformance.py`
- `tests/test_v102_remaining_blockers.py`

## V101-B04 — B11 persistence / idempotency / recovery / audit

Implemented:
- Content-addressed immutable blobs.
- Immutable authority records separated from mutable projection/currentness rows.
- Versioned currentness pointers.
- Durable idempotency positions bound to recovery epoch.
- RecoveryEpoch advancement only after verified backup assessment.
- Tamper-evident chained audit events.
- Immutable authority commit-set records bind audit identity to authority-changing actions.
- Cross-store publication record binds structured candidate authority to exact blob identity and publication standing.

Evidence:
- `src/ra_agent_studio/infra/sqlite.py`
- `src/ra_agent_studio/application/control_plane.py`
- `tests/test_v102_governance_conformance.py`
- `tests/test_v102_remaining_blockers.py`

## V101-B05 — controlled execution trust boundary

Implemented:
- No host-subprocess fallback.
- Docker/Podman OCI boundary required; otherwise fail closed.
- Network disabled.
- Read-only root filesystem.
- All Linux capabilities dropped.
- no-new-privileges.
- PID, memory and CPU limits.
- Isolated tmpfs.
- Non-root execution.
- Only exact module source mounted read-only.
- No host environment or secrets forwarded.
- Fixture, input, executor, environment, execution-policy and termination identities persisted with observations.

Evidence:
- `src/ra_agent_studio/infra/execution.py`
- `src/ra_agent_studio/domain/effect.py`
- `tests/test_repair_blockers.py`
- `tests/test_v102_remaining_blockers.py`

## V101-B06 — module authority / exact requirement / capability contract

Implemented:
- ModuleType, ModuleAuthorityClass and editability preserved end-to-end.
- Shared/frozen module mutation is a non-bypassable SharedChangeRequired STOP in Studio.
- One exact AgentRequirement and AgentAuthorityBoundary bind a composition.
- Required capabilities must have exactly one provider.
- Exact capability-provider bindings are identity-bearing.
- Studio→Factory request carries exact module classification, requirement/boundary and provider binding identity.
- Factory bridge rejects unsupported classification, missing/ambiguous/synthesized providers and capability-binding identity drift.

Evidence:
- `src/ra_agent_studio/domain/module.py`
- `src/ra_agent_studio/domain/composition.py`
- `src/ra_agent_studio/infra/factory.py`
- `scripts/factory_v111_bridge.py`
- `tests/test_v102_remaining_blockers.py`

## V101-B07 — B10 deployment / B12 application control plane

Implemented:
- Deployment authorization is separate from activation.
- Immutable runtime-realization snapshot binds runtime profile, environment, provider, secret scope, permission scope, policy and runtime boundary.
- Activation performs current baseline/version, grant/safety, RecoveryEpoch and realization-drift checks.
- Activation attempts survive ambiguous external side-effect outcomes and require explicit reconciliation.
- Hold, revoke, stop, target supersession and revalidation use Frozen B10-equivalent legal state edges.
- Closed ApplicationOperationCatalog mirrors Frozen Factory governance/factory/deployment descriptors.
- CommandEnvelope requires exact target, authenticated principal, workspace, idempotency key and ExpectedRecoveryEpoch.
- API and CLI project the closed command surface; caller request bodies do not mint principal authority.

Evidence:
- `src/ra_agent_studio/domain/deployment.py`
- `src/ra_agent_studio/application/operation_catalog.py`
- `src/ra_agent_studio/application/control_contracts.py`
- `src/ra_agent_studio/application/control_plane.py`
- `src/ra_agent_studio/api.py`
- `src/ra_agent_studio/cli.py`
- `tests/test_v102_remaining_blockers.py`

## Frozen boundaries preserved

The v1.02 repair does not reopen:
- Frozen Architecture B01–B13.
- Frozen Implementation Handoff.
- Frozen Factory v1.11.
- Exact V8 FROZEN reference.

Review, freeze, canonical promotion and deployment remain distinct authority functions.

## Final submission requirement

The exact final v1.02 source commit must separately have:
1. cumulative Python 3.14.7 regression PASS,
2. API import PASS,
3. production container build PASS,
4. exact live integration PASS against Frozen Factory v1.11 / V8 FROZEN,
5. exact Candidate archive SHA/size/source identity.

External re-review remains the authority for blocker closure and software-freeze authorization.

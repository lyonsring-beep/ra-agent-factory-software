# RA Agent Studio — v1_00 External Review Repair Map

## Review standing

- `RA_AGENT_STUDIO_IMPLEMENTATION_CANDIDATE_v1_00`: **FAIL**
- Open substantive blockers reported by external review: **7**
- Architecture reopen: **NOT REQUIRED**
- Frozen Factory v1.11 reopen: **NOT REQUIRED**
- Software Freeze: **NOT AUTHORIZED**
- Repair lineage: `v1_00 → v1_01`

This document is an implementation-repair map. It does not declare external-review closure.

## B01 — Review authority / independence

Repair:
- server-owned `Principal` and `AuthorityGrant`
- authenticated bearer credential resolves Principal; request body cannot manufacture reviewer identity
- review grant is scoped by workspace, authority function, approved review method and expiry
- exact candidate contribution principals are recorded
- reviewer must be independent of all recorded contributors and the grant must explicitly attest that independence
- no public API exists to mint production authority grants

Primary code:
- `src/ra_agent_studio/domain/auth.py`
- `src/ra_agent_studio/domain/review.py`
- `src/ra_agent_studio/api.py`

Evidence tests:
- `tests/test_repair_blockers.py::test_review_cannot_be_manufactured_from_two_names`
- `tests/test_repair_blockers.py::test_review_requires_method_scope_workspace_and_contribution_independence`

## B02 — PASS Review must bind exact Candidate bytes

Repair:
- `CandidateRecord` owns exact `candidate_id` + SHA-256
- `ReviewRecord` binds exact candidate ID/hash/workspace
- freeze checks review candidate ID, exact candidate hash and workspace before creating FrozenArtifact
- API freeze accepts Candidate ID + Review ID, not a caller-selected artifact hash

Primary code:
- `src/ra_agent_studio/domain/candidate.py`
- `src/ra_agent_studio/domain/review.py`
- `src/ra_agent_studio/domain/governance.py`

Evidence tests:
- `tests/test_repair_blockers.py::test_pass_review_is_exactly_bound_to_candidate_hash`
- `tests/test_review_freeze_deploy.py::test_review_for_different_candidate_cannot_freeze`

## B03 — Production persistence / transaction / audit

Repair:
- durable SQLite authoritative store
- WAL + explicit `BEGIN IMMEDIATE` write transactions
- rollback/commit boundary on authority transitions
- durable canonical records and append-only audit events
- runtime Compose mounts persistent data volume
- restart persistence test covers Review / Freeze / Baseline / Deployment / Audit

Primary code:
- `src/ra_agent_studio/infra/sqlite.py`
- `src/ra_agent_studio/application/studio.py`
- `compose.yaml`

Evidence test:
- `tests/test_repair_blockers.py::test_authoritative_records_survive_restart`

## B04 — Real frozen Factory v1.11 integration

Repair implemented in code:
- production build has no simulated hash/string fallback
- `SubprocessFactoryRuntime` requires an actual Factory bridge command
- Studio sends exact authoritative module bytes/config identities
- bridge verifies exact frozen Factory source commit, exact v1.11 Candidate bytes and exact accepted V8 evidence identity
- bridge invokes frozen Factory v1.11 `ModuleRegistryService`, `CompositionService` and `CandidateBuildService`
- Studio independently hashes Factory-produced Candidate bytes and Factory evidence
- exact Factory runtime/candidate identities are bound into Studio `BuildEvidence`

Primary code:
- `src/ra_agent_studio/infra/factory.py`
- `scripts/factory_v111_bridge.py`
- `src/ra_agent_studio/domain/evidence.py`

Required closure evidence:
- live cross-repository workflow against exact Factory commit `bc0568926ef70ea6fa7e5e6cc8287c09e041fb4f`
- exact frozen Factory Candidate SHA-256 `8387b7aa27d39be56a4f1e28ae979f9f233b1f29c196b5339c1b40dd6fdfec7b`
- exact accepted V8 evidence SHA-256 `abb7faf63db08c00f6d2d94e5c336735285e803dccf0f7da92481a86501fc626`

Standing: **IMPLEMENTATION REPAIRED / LIVE EVIDENCE RUN REQUIRED BEFORE CLOSURE CLAIM**.

## B05 — Effect Sandbox stub

Repair:
- exact revision executes in a separate isolated Python process (`python -I`)
- fixture input is passed on stdin and actual stdout becomes observation
- before/after executions produce an actual `TestDelta`
- sandbox output is observation-only and carries no governance authority

Primary code:
- `src/ra_agent_studio/infra/execution.py`
- `src/ra_agent_studio/domain/effect.py`

Evidence test:
- `tests/test_repair_blockers.py::test_effect_sandbox_executes_real_module_and_computes_delta`

## B06 — Composition compatibility semantics

Repair:
- exact revision/content/config identities are bound
- required capability provider validation
- required module validation
- explicit incompatible module validation
- config identity requirement
- identity-domain collision validation
- dependency-cycle validation
- `CompatibilityIssue` is now on the realization path and failures are fail-closed

Primary code:
- `src/ra_agent_studio/domain/module.py`
- `src/ra_agent_studio/domain/composition.py`

Evidence tests:
- `tests/test_composition.py`

## B07 — Freeze / Baseline / Deployment authority plane

Repair:
- Review, Freeze, Baseline Promotion and Deployment are separate grants and transitions
- Freeze requires exact reviewed Candidate
- baseline promotion executes in a write critical section
- actual current baseline must equal expected predecessor
- Candidate must have been built from that exact predecessor
- current baseline pointer changes atomically with promotion
- deployment requires separate deployment grant
- activation-time current baseline must contain the exact FrozenArtifact
- transitions are durably audited

Primary code:
- `src/ra_agent_studio/domain/governance.py`
- `src/ra_agent_studio/domain/auth.py`
- `src/ra_agent_studio/application/studio.py`

Evidence test:
- `tests/test_repair_blockers.py::test_freeze_promotion_and_deployment_are_distinct_authority_transitions`

## Candidate gate

`v1_01` must not be packaged as the final re-review Candidate until:

1. repair-branch CI is green,
2. the live exact Factory v1.11 integration run is green,
3. the live Factory evidence artifact is captured and identity-recorded,
4. the exact v1_01 source commit is fixed,
5. a fresh full implementation Candidate is packaged from that exact commit.

Internal CI PASS is evidence only; it is not an external Implementation Approval PASS.

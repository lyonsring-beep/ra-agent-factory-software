# RA Agent Studio — v1_00 External Review Repair Map

## Review standing

- `RA_AGENT_STUDIO_IMPLEMENTATION_CANDIDATE_v1_00`: **FAIL**
- Open substantive blockers reported by external review: **7**
- Architecture reopen: **NOT REQUIRED**
- Frozen Factory v1.11 reopen: **NOT REQUIRED**
- Software Freeze: **NOT AUTHORIZED**
- Repair lineage: `v1_00 → v1_01`

This document is an implementation-repair map. It records implementation evidence but does not declare external-review closure or authorize Freeze.

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

Repair:
- production build has no simulated hash/string fallback
- `SubprocessFactoryRuntime` requires an actual Factory bridge command
- Studio sends exact authoritative module bytes/config identities
- bridge verifies exact frozen Factory source commit, exact v1.11 Candidate bytes and the exact frozen V8 transport package identity
- bridge invokes frozen Factory v1.11 `ModuleRegistryService`, `CompositionService` and `CandidateBuildService`
- Studio independently hashes Factory-produced Candidate bytes and Factory evidence
- exact Factory runtime/candidate identities are bound into Studio `BuildEvidence`

Primary code:
- `src/ra_agent_studio/infra/factory.py`
- `scripts/factory_v111_bridge.py`
- `src/ra_agent_studio/domain/evidence.py`

Exact frozen Factory anchors:
- Factory source commit: `bc0568926ef70ea6fa7e5e6cc8287c09e041fb4f`
- Factory v1.11 Candidate SHA-256: `8387b7aa27d39be56a4f1e28ae979f9f233b1f29c196b5339c1b40dd6fdfec7b`
- Frozen V8 package artifact ID: `10334979844`
- Frozen V8 package source run: `34813046629`
- Frozen V8 package SHA-256: `df04ac7cc938be23d7652fa8424dd50f220ed95941c1e6290e689c04bbaceeaa`

Live integration evidence:
- Integration run: `35063339693`
- Job: `104688177084`
- Result: `SUCCESS`
- Python: `3.14.7`
- Studio source exercised: `00bcc9a2f80cd4ed72d6440dec7a9a8639e84a79`
- Standing emitted by live run: `LIVE_FACTORY_INTEGRATION_PASS`
- Real Factory-produced artifact SHA-256: `542e896d1b5e4c2577e20d155d26dbd0406b7924b6657acb1224dfcdab0d8c57`
- Real Factory evidence SHA-256: `1e373b008a921c16a4fb3b6247bc28a8ec6a00da4f3d202951ae87b5237c76ac`
- Integration record SHA-256: `ae8a7217673e42aa0125e390a702157cf36001899c0f76c61befc7ec5e1afa42`
- Uploaded evidence artifact: `RA_AGENT_STUDIO_v1_01_FACTORY_v1_11_LIVE_INTEGRATION_EVIDENCE`
- Evidence artifact ID: `10433845504`
- Evidence artifact size: `37,440 bytes`
- Evidence artifact ZIP SHA-256: `4017f278bd618a142c60d06604e52cbfdbf7c4713ddcfe43383268a4cbab3164`

Standing: **IMPLEMENTATION REPAIR EVIDENCE SATISFIED INTERNALLY / EXTERNAL RE-REVIEW REQUIRED FOR CLOSURE**.

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
- `CompatibilityIssue` is on the realization path and failures are fail-closed

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

For `v1_01`, the implementation-side prerequisites are now materially satisfied: repair CI is green and the exact frozen Factory v1.11 live integration has run successfully. A fresh v1_01 Candidate must still be packaged from one exact source commit and externally re-reviewed.

Internal CI or live-integration PASS is implementation evidence only. It is not an external Implementation Approval PASS and does not authorize Software Freeze.

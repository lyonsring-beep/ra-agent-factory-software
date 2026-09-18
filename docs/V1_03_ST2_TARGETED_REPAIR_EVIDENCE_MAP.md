# RA Agent Studio v1.03 — ST2 Targeted Implementation Repair Evidence Map

Status: INTERNAL CANDIDATE PREPARATION / EXTERNAL RE-REVIEW NOT YET PERFORMED

Authorized repair scope: ST2-B01 through ST2-B05 only. Previously closed v1.02 areas are preserved and are not reopened.

## ST2-B01 — B09 canonical promotion lock ordering

Repair:
- Exact freeze now acquires the canonical promotion lock before predecessor currentness assessment.
- The current-baseline pointer is read only after that lock is held.
- Exact freeze is recorded under the same fencing token.
- The lock remains held across the freeze→canonical-promotion boundary.
- Canonical pointer update verifies the same holder/token and then releases the lock.
- Stale predecessor detection occurs under the lock; the stale path records PR-15R routing and releases the lock without freezing.

Regression evidence:
- `tests/test_v103_residual_blockers.py::test_st2_b01_lock_precedes_currentness_and_is_continuous_to_promotion`
- Existing PR-15R and fencing tests remain green.

## ST2-B02 — single public B12 Control Plane

Repair:
- Public API mutation surface is now only `POST /commands`.
- Legacy direct mutation routes for modules, reviews, freezes, baselines and deployments are no longer registered.
- CLI direct `create-module` mutation was removed; CLI mutations use `submit-command`.
- `StudioControlPlane` now projects module-revision-create, composition-realize, candidate-build, controlled-execution-run, review-decision-ingest, exact-freeze, canonical-promote and deployment lifecycle operations.
- Authenticated bearer principal is server-derived and cannot be supplied in command payload.

Regression evidence:
- `tests/test_v103_residual_blockers.py::test_st2_b02_only_commands_is_public_mutation_api`
- `tests/test_api.py`
- `tests/test_api_governance.py`

## ST2-B03 — atomic idempotency + authority mutation

Repair:
- SQLite authoritative transactions now support nested SAVEPOINTs.
- `StudioControlPlane.execute()` owns one outer authoritative transaction for the mutation plus idempotency record plus immutable CommandCommit record.
- Service transactions execute as nested SAVEPOINTs under that same commit.
- If any step before commit fails, both the authority mutation and idempotency result roll back together.
- External runtime side effects use a separate durable-attempt protocol: activation/stop attempt + command idempotency commit first; provider execution happens only after that durable reservation exists.
- Provider receives the durable attempt id as provider idempotency key, allowing crash recovery/retry against the same attempt.

Regression evidence:
- `tests/test_v103_residual_blockers.py::test_st2_b03_authority_mutation_and_idempotency_rollback_together`
- Existing idempotency/recovery-epoch tests remain green.

## ST2-B04 — real runtime provider/launcher

Repair:
- Synthetic `studio-runtime:<UUID>` activation is disabled.
- Production runtime launch/stop uses a server-configured `RuntimeLauncher` adapter.
- The subprocess production adapter sends bounded JSON to configured provider commands and fails closed when not configured.
- Activation uses durable attempt → provider launch → explicit ACTIVATED / FAILED / AMBIGUOUS reconciliation.
- An ACTIVATED result requires an exact external runtime identity.
- Stop uses durable stop attempt → provider stop → STOPPED only after provider confirmation.
- Provider timeout/exception/non-JSON result remains AMBIGUOUS/STOPPING rather than claiming success.
- Provider calls receive activation/stop attempt IDs as idempotency keys.

Regression evidence:
- `tests/test_v103_residual_blockers.py::test_st2_b04_activation_uses_durable_attempt_and_preserves_ambiguous`
- `tests/test_v103_residual_blockers.py::test_st2_b04_confirmed_provider_is_required_for_active_and_stopped`

## ST2-B05 — bounded Authoring Authority

Repair:
- `AuthorityScope.DESIGN_AUTHORING` and `AuthorityScope.IMPLEMENTATION_AUTHORING` are explicit server-owned scopes corresponding to AF-03/AF-04.
- `create_module_revision()` and `prepare_candidate()` require IMPLEMENTATION_AUTHORING.
- `compose()` requires DESIGN_AUTHORING.
- Authoring commands are bound to the grant workspace; authentication alone is insufficient.
- Existing BUILD authority remains separate for candidate build.

Regression evidence:
- `tests/test_v103_residual_blockers.py::test_st2_b05_authentication_is_not_authoring_authority`

## Preserved closed scope

No Architecture reopen.
No Frozen B01–B13 reopen.
No Implementation Handoff reopen.
No Factory v1.11 reopen.
The v1.02 exact Frozen Factory integration PASS remains the accepted Factory reference:
- Factory V8 FROZEN Artifact ID: 10334979844
- Factory V8 FROZEN SHA256: df04ac7cc938be23d7652fa8424dd50f220ed95941c1e6290e689c04bbaceeaa
- Factory commit: bc0568926ef70ea6fa7e5e6cc8287c09e041fb4f
- Factory Candidate SHA256: 8387b7aa27d39be56a4f1e28ae979f9f233b1f29c196b5339c1b40dd6fdfec7b
- v1.02 exact-source live integration Run: 35324637522

External re-review remains the only authority that may mark ST2-B01…ST2-B05 CLOSED and authorize Software Freeze.

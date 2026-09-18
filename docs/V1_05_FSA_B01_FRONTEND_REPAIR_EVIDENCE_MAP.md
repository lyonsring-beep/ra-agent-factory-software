# RA Agent Studio v1.05 — FSA-B01 Targeted Frontend Repair Evidence Map

Status: IMPLEMENTATION CANDIDATE PREPARATION / TARGETED EXTERNAL IMPLEMENTATION RE-REVIEW REQUIRED

Authorized repair scope is limited to FSA-B01: Studio frontend delivery layer plus directly required tests/evidence.

## Review finding addressed

The v1.04 Full System Acceptance review found that the exact Frozen v1.04 frontend still posted to legacy mutation endpoints while the exact Frozen backend accepted authoritative mutations only through `POST /commands`.

The post-freeze integration UI had corrected that mismatch, but it was not part of the Frozen v1.04 implementation. Therefore Full System Acceptance could not rely on it.

## v1.05 targeted repair

The corrected UI behavior is now incorporated into the new Studio implementation Candidate itself:

- `web/app.js` sends every authoritative mutation through the existing B12 `/commands` control plane.
- The command envelope carries `command_id`, `operation_descriptor_id`, `exact_target_ref`, `workspace_ref`, `idempotency_key`, `expected_recovery_epoch`, and `payload`.
- Legacy public mutation calls are removed from the frontend.
- `web/index.html` exposes bearer token, workspace and RecoveryEpoch session inputs required by the Frozen backend contract.
- `web/nginx.conf` provides the same-origin `/api/` reverse proxy to the API service.
- `compose.yaml` mounts that exact nginx configuration for the delivered frontend.

## Preserved implementation surfaces

This repair does not alter backend/domain semantics.

The candidate packaging workflow asserts that the v1.04 → v1.05 delta is restricted to:

- `web/**`
- `compose.yaml`
- directly required `tests/**`
- directly required `docs/**`
- the v1.05 packaging workflow itself

Any change under `src/**`, `scripts/**`, or other implementation surfaces causes packaging to fail closed.

## Regression evidence

`tests/test_v105_frontend_delivery.py` verifies:

1. all explicit UI POST mutations converge on `/commands`;
2. legacy mutation routes are absent from the frontend implementation;
3. required CommandEnvelope fields are emitted;
4. same-origin `/api` proxy delivery is configured.

The full cumulative Python regression remains mandatory before packaging.

## Next gate

After the exact v1.05 Candidate passes cumulative regression:

1. targeted external implementation re-review of FSA-B01 only;
2. if PASS, mechanical freeze of the exact approved v1.05 Candidate;
3. Full System Acceptance rerun must serve the exact newly Frozen `studio-frozen/web` bytes or assert full web-directory byte equality before browser testing.

No Architecture, Factory v1.11, Handoff, or accepted backend semantics are reopened.

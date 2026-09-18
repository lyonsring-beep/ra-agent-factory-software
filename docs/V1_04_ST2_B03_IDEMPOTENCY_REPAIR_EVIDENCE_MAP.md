# RA Agent Studio v1.04 — ST2-B03 Residual IdempotencyKey Repair Evidence Map

Status: INTERNAL CANDIDATE PREPARATION / EXTERNAL TARGETED RE-REVIEW NOT YET PERFORMED

Authorized repair scope: ST2-B03 residual blocker only.

## External-review residual blocker

Frozen B11 defines `IdempotencyKey` as the stable retry identity for one logical command/effect request.

Required behavior:

```text
same IdempotencyKey + same logical request
→ REPLAY original result

same IdempotencyKey + different logical request
→ CONFLICTING_REUSE
→ FAIL CLOSED
```

v1.03 incorrectly keyed `idempotency_records` and lookup by `command_id`.

## v1.04 repair

- `idempotency_records.idempotency_key` is now the authoritative PRIMARY KEY.
- `command_id` remains provenance only and is not the dedup key.
- `StudioControlPlane.execute()` resolves prior positions with `command.idempotency_key`.
- Request identity excludes `command_id`, so a retry may use a new CommandId while preserving the same logical IdempotencyKey/request.
- Same key + same request returns `REPLAYED` with the original result and original CommandId provenance.
- Same key + different request returns `CONFLICTING_REUSE` and performs no mutation.
- Idempotency position + authority mutation remain in the same authoritative transaction established by v1.03.
- Immutable `command_commit` now explicitly records `idempotency_key`.
- v1.03 database schema is migrated to the v1.04 IdempotencyKey-primary schema; legacy rows are preserved under a namespaced legacy key because v1.03 did not persist the original IdempotencyKey.

## Required adversarial regression evidence

`tests/test_v104_idempotency_key.py` contains both externally requested cases:

1. `same idempotency_key + different command_id + same request → REPLAYED`
2. `same idempotency_key + different request → CONFLICTING_REUSE / fail closed`

Existing cumulative regression remains required.

## Preserved closures

The v1.04 repair does not reopen:
- ST2-B01
- ST2-B02
- ST2-B04
- ST2-B05
- Frozen Architecture B01–B13
- Frozen Implementation Handoff
- Frozen Factory v1.11

Accepted Factory reference remains:
- V8 FROZEN Artifact ID: `10334979844`
- V8 FROZEN SHA256: `df04ac7cc938be23d7652fa8424dd50f220ed95941c1e6290e689c04bbaceeaa`
- Factory commit: `bc0568926ef70ea6fa7e5e6cc8287c09e041fb4f`
- Factory Candidate SHA256: `8387b7aa27d39be56a4f1e28ae979f9f233b1f29c196b5339c1b40dd6fdfec7b`
- Accepted exact-source live integration Run: `35324637522`
- Live integration Artifact ID: `10538791989`
- Live integration Artifact SHA256: `6eb21fcb24b9d9a6b68b9b02a332f548116dfcf37afd3fd52f88c97af0130e2d`

External targeted re-review remains the only authority that may mark ST2-B03 CLOSED and authorize Software Freeze.

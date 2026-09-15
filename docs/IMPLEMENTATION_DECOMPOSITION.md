# RA Agent Studio — Software Implementation Decomposition

## Purpose

This decomposition turns the frozen RA Agent Studio Formal Software Design into implementation work without reopening design semantics.

## I01 — Authoritative Control Plane Foundation

Implements B01, B02, B08, B11, and the authoritative parts of B12.

Deliverables:

- typed domain identities for module, revision, hash, baseline, lineage, candidate, frozen artifact, and deployment record
- authoritative command handling
- state-transition guards
- event/audit recording
- transactional persistence boundary
- projection/read-model boundary for UI consumption

Exit condition: backend can persist and enforce the frozen authority/state model without UI ownership of facts.

## I02 — Module Library

Implements the governed inventory of exact module revisions.

Deliverables:

- module/revision registration and lookup
- exact identity and hash binding
- lifecycle state projection
- backend queries for the Module Library UI

## I03 — Module Lab

Implements controlled module-edit / candidate preparation flow under the frozen lifecycle rules.

Deliverables:

- candidate derivation from exact predecessor revision
- validation and controlled edit boundary
- comparison-ready candidate output
- no approval/freeze authority in the Lab surface

## I04 — Effect Sandbox

Implements B04 effect fixtures/comparison.

Deliverables:

- controlled fixture execution
- before/after observation
- TestObservation / TestDelta representation
- typed warnings and evidence binding
- no authority escalation from test output

## I05 — Composition / Compatibility

Implements B05.

Deliverables:

- composition graph/model
- compatibility checks
- exact module revision binding
- `RealizedAgentComposition` generation boundary

## I06 — Realization / Build / Evidence

Implements B06.

Deliverables:

- deterministic realization/build orchestration
- evidence capture
- source/build/runtime identity binding
- reproducibility metadata

## I07 — Review / Repair

Implements B07.

Deliverables:

- independent review record model
- blocker and repair flow
- review result projection
- no implicit freeze on PASS

## I08 — Freeze / Promotion / Baseline / Lineage

Implements B08/B09 authority transitions.

Deliverables:

- exact freeze operation
- immutable frozen identity
- baseline designation
- lineage advancement
- promotion separated from review and deployment

## I09 — Deployment Authority

Implements B10.

Deliverables:

- deployment eligibility checks
- deployment approval boundary
- only FrozenArtifact may enter deployment path
- deployment records and audit trail

## I10 — API / CLI / Coding-Agent Interface

Completes B12 after the authoritative control plane is stable.

Deliverables:

- stable command/query API
- CLI surface
- coding-agent interface
- explicit authority boundaries identical to backend rules

## I11 — Studio Frontend

Implements B13 and the canonical UX sequence.

Primary navigation:

`Module Library → Module Lab → Effect Sandbox → Agent Canvas`

Frontend rules:

- frontend reads backend projections
- frontend submits commands
- frontend never manufactures authoritative state
- authority/state/history views must reflect backend truth

## I12 — Integration / Runtime / Acceptance

Integrates the frozen Factory v1.11 runtime foundation with the Studio product implementation.

Deliverables:

- end-to-end environment
- persistence and object/runtime integration
- production build
- regression suite
- acceptance evidence
- final implementation review/freeze package

## First execution order

Begin with I01. Do not start UI-first implementation. I01 establishes the authority, identity, state-machine, transaction, and audit substrate required by every downstream surface.

# RA Agent Studio — Implementation Acceptance Criteria

The implementation candidate is ready for final external review only when all criteria below are evidenced.

1. I01: authoritative state/authority transitions are backend-enforced and audited.
2. I02: Module Library stores and reads exact revision/hash identity.
3. I03: Module Lab derives candidates without approval/freeze authority.
4. I04: Effect Sandbox produces observations/deltas with no authority escalation.
5. I05: Composition binds exact module revisions and rejects duplicate/incompatible bindings.
6. I06: realization/build emits artifact identity and reproducibility evidence tied to the frozen Factory runtime identity.
7. I07: review independence and PASS/FAIL/blocker semantics are enforced; PASS does not freeze.
8. I08: freeze, baseline and lineage are distinct explicit records.
9. I09: deployment accepts only FrozenArtifact identity.
10. I10: API/CLI/coding-agent command surfaces preserve the same backend authority rules.
11. I11: Studio frontend implements the canonical Module Library → Module Lab → Effect Sandbox → Agent Canvas workflow and acts only as projection/command surface.
12. I12: complete end-to-end acceptance path runs from module revision through controlled deployment and all tests pass in CI.

A successful internal test run is not an external review verdict. Final review occurs after implementation completion.
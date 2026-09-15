# RA Agent Studio — Canonical Implementation Baseline

## Status

`IMPLEMENTATION BASELINE / DERIVED FROM FROZEN DESIGN`

This repository implements the already-approved RA Agent Studio Formal Software Design. It does not redefine product architecture.

## Canonical architecture blocks

The accepted formal software design is organized as B01–B13:

1. Authority / trust boundary
2. Identity / revision / hash / lineage
3. Module lifecycle
4. Effect fixtures / comparison
5. Composition / compatibility
6. Realization / build / evidence
7. Review / independence / repair
8. Production state machine
9. Exact freeze / promotion / baseline / lineage
10. Deployment authority
11. Persistence / transactions / audit
12. Application control plane / API / CLI / coding-agent interface
13. Frontend projection / UX

## Frozen semantic invariants

- Manual Pipeline has no approval authority.
- Backend state is authoritative.
- UI never owns authoritative facts.
- Revision, hash, baseline, and lineage are first-class identities.
- Authority changes are evented and auditable.
- Review, Freeze, Promotion, and Deployment are separate authorities and transitions.
- Candidate and approved-but-unfrozen states cannot deploy.
- Only a FrozenArtifact may enter the separate deployment-approval path.
- P3 Research Producer, P8 Knowledge Steward, and P7 Formal-State Registrar are external frozen test assets only.

## Product UX

Canonical user flow:

`Module Library → Module Lab → Effect Sandbox → Agent Canvas`

Modules are exact-revision-governed building blocks. Composition produces a `RealizedAgentComposition`. The UI submits commands and reads backend projections; the backend state machine remains authoritative.

## Initial software architecture

The implementation begins as a **domain-modular monolith with strong transactional consistency**.

Implementation sequencing is control/data plane first, then Module Library/Lab, Effect Sandbox, Composition, Build, Tests/Evidence, Review, Freeze/Baseline/Lineage, Deployment, and finally coding-agent API/CLI integration.

## Upstream runtime foundation

RA Agent Factory Implementation v1.11 Frozen is the accepted runtime / production foundation. Studio implementation must consume or integrate that foundation without reopening its frozen architecture or implementation semantics.

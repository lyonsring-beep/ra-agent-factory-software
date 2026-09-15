# RA Agent Studio Software

This repository is the implementation repository for **RA Agent Studio**.

## Canonical inputs

- RA Agent Studio Formal Software Design package: canonical upstream design source.
- RA Agent Factory Implementation v1.11 Frozen: runtime / agent-production foundation.
- Frozen architecture boundaries and invariants from the accepted B01–B13 design remain authoritative.

## Product boundary

RA Agent Studio is the software product layer. It does not reopen the frozen RA Agent Factory architecture or implementation.

Hard boundaries preserved:

- Factory ≠ Research OS.
- Review ≠ Freeze ≠ Promotion ≠ Deployment.
- Manual Pipeline has no approval authority.
- Backend authoritative state is canonical; the UI is a projection and command surface.
- Baseline / lineage / revision / hash identity are first-class.
- Freeze authority is separate from deployment authority.
- Candidate and approved-but-unfrozen states are not deployable.
- P3 Research Producer, P8 Knowledge Steward, and P7 Formal-State Registrar remain external frozen test assets, not bundled product modules.

## Implementation sequence

The implementation follows the canonical design sequence:

1. authoritative control/data plane
2. Module Library / Module Lab
3. Effect Sandbox
4. composition / compatibility
5. realization / build / evidence
6. tests / review / repair
7. freeze / baseline / lineage
8. deployment authority
9. coding-agent API / CLI
10. frontend integration and UX completion

The initial system shape is a **domain-modular monolith with strong transactional consistency**.

## Primary UX flow

`Module Library → Module Lab → Effect Sandbox → Agent Canvas`

Implementation work must derive from the frozen Studio design package. New product semantics must not be invented in code without a formal design reopen.

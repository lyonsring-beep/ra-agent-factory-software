# RA Agent Studio v1.04 — Integration / Runtime Harness

This directory is downstream of the frozen Studio implementation.

Frozen Studio implementation identity:
- source commit: `6cd2e99a726893516e31fb8c9c7c4534aa2a46d1`
- approved Candidate SHA256: `046d1a159aae7ace9c1a552f20f37d14b8c19f917d6ab5b027299e1d5acb3929`
- mechanical Frozen artifact: `RA_AGENT_STUDIO_IMPLEMENTATION_v1_04_FROZEN`, Artifact ID `10541843870`

This harness does not mutate frozen implementation source. It checks out that exact source separately and exercises:
1. API health / command plane
2. bounded authoring
3. controlled execution sandbox
4. real Frozen Factory v1.11 build
5. review → freeze → canonical baseline promotion
6. deployment authorization
7. external runtime-provider launch
8. provider-confirmed stop
9. IdempotencyKey replay
10. persistent authoritative projection

Passing this harness is integration/runtime evidence, not a redesign or a new implementation approval.

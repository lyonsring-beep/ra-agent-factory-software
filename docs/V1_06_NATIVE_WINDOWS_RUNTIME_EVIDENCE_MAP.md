# RA Agent Studio v1.06 — Native Windows Runtime Targeted Implementation Evidence Map

Status: IMPLEMENTATION CANDIDATE PREPARATION

## Change purpose

RA Agent Studio v1.05 is system-accepted. Its controlled execution boundary is OCI-only and intentionally fails closed when Docker/Podman is absent.

v1.06 adds a second explicit controlled-execution provider for native Windows so the installed desktop release can run without Docker Desktop while preserving the authoritative Studio/Factory/domain semantics.

## Authorized / intended change surface

Implementation delta is intentionally narrow:

- `src/ra_agent_studio/infra/execution.py`
- `src/ra_agent_studio/application/studio.py`
- directly required Windows-native tests/evidence/packaging metadata

No Factory v1.11 code, authority semantics, B12 command plane, review/freeze/promotion semantics, deployment state machine, persistence model, frontend, or API route is changed.

## Windows-native controlled execution boundary

The provider is explicit: `RA_STUDIO_CONTROLLED_EXECUTION_PROVIDER=windows-native`.

It requires a dedicated sandbox Python interpreter and a Windows Firewall outbound-block rule bound to that exact executable. It fails closed if the rule is absent or mismatched.

Each execution:

1. uses isolated Python mode `-I -S`;
2. receives only an allowlisted environment (no parent secrets);
3. runs from a disposable working directory;
4. marks the exact module source read-only;
5. is placed in a Windows Job Object;
6. enforces active-process limit = 1;
7. enforces process-memory limit = 128 MiB;
8. kills the entire Job Object on timeout;
9. requires outbound network to be blocked by the installer-provisioned Windows Firewall rule.

The provider does not silently fall back to an unsafe host subprocess.

## Test obligations

Windows-native CI must demonstrate:

- API initialization with the native provider;
- exact stdin/stdout module execution;
- parent secret environment is not inherited;
- outbound network connection is blocked;
- child process creation is blocked by the Job Object;
- missing firewall guard fails closed.

The existing cumulative Linux/OCI regression remains required to prove the new provider does not regress the accepted v1.05 path.

## Review / freeze boundary

v1.05 remains Frozen and Accepted.

v1.06 is a new implementation Candidate. It must receive targeted implementation review before any v1.06 Software Freeze or native Windows release is treated as accepted.

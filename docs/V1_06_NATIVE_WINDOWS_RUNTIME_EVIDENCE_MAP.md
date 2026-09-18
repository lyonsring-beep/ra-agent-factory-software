# RA Agent Studio v1.06 — Native Windows Runtime Targeted Implementation Evidence Map

Status: REVISED IMPLEMENTATION CANDIDATE PREPARATION

## Review basis

Prior targeted review:
`RA_AGENT_STUDIO_v1_06_TARGETED_IMPLEMENTATION_REVIEW_v1_01_FAIL`

Authorized reopen scope is limited to the Windows-native controlled-execution implementation plus directly required tests/evidence. Architecture, Factory v1.11, frontend, API command plane, review/freeze/promotion semantics, persistence, deployment state machine, and accepted v1.05 baseline remain closed.

## Blocker-directed repair

### V106-B01 — host resource isolation

Repair: Windows-native mutable module execution now runs inside a no-capability Windows AppContainer.

The AppContainer removes ambient same-user host authority. The only resources explicitly brokered are:

- dedicated Python runtime directory: RX only;
- per-execution disposable sandbox directory: Modify;
- inherited Windows platform resources required for process startup.

No broad filesystem capability or network capability is granted.

Adversarial tests prove the module cannot:

- read a host sentinel outside the sandbox;
- modify a host sentinel outside the sandbox;
- read/modify a host HKCU registry sentinel.

The host sentinel remains unchanged after attempted access.

### V106-B02 — pre-assignment execution race

Repair: the native module process is created using:

- `PROC_THREAD_ATTRIBUTE_SECURITY_CAPABILITIES` with the AppContainer SID;
- `CREATE_SUSPENDED`;
- Windows Job Object with active-process limit = 1, 128 MiB process-memory limit, and kill-on-close.

The startup order is fail-closed:

`CreateProcessW(CREATE_SUSPENDED + AppContainer) -> configure/attach Job Object -> verify success -> ResumeThread`.

On any creation, AppContainer, Job assignment, or resume failure, the process is terminated and execution fails closed.

An adversarial test inspects the primary thread suspend count during Job attachment and proves it remains suspended before containment is attached.

## Preserved controls

The provider remains explicit through `RA_STUDIO_CONTROLLED_EXECUTION_PROVIDER=windows-native`.

Additional preserved controls:

- Python isolated mode `-I -S`;
- allowlisted environment only, with no inherited parent secret variables;
- AppContainer has no network capability, so outbound network is denied;
- active child-process count is limited by Job Object;
- timeout terminates the Job Object;
- no unsafe host-subprocess fallback;
- OCI provider remains unchanged for the accepted v1.05/Linux path.

## Exact revised Windows evidence

Native Windows CI run:
`35347019034`

Tested source commit:
`cc44ddef00599e5512801d230e9b1d5fc31e20c0`

Evidence artifact:
`RA_AGENT_STUDIO_v1_06_NATIVE_WINDOWS_RUNTIME_EVIDENCE`

Artifact ID:
`10547013028`

Outer artifact SHA256:
`c5be564f30bee21e54eebe55eae89a0cef61160d0bb66edb338257f2dc030d40`

Observed:
- `WINDOWS_APPCONTAINER_RUNTIME_PROVISIONED`
- `WINDOWS_NATIVE_API_IMPORT_PASS`
- provider identity starts with `controlled-windows-appcontainer-python-v2`
- `10 passed`

## Cumulative regression requirement

The revised Candidate must also re-run the full Linux/OCI cumulative regression and must preserve all v1.05 accepted surfaces byte-for-byte outside the authorized Windows-native repair scope.

## Review / freeze boundary

v1.05 remains Frozen and System-Accepted.

v1.06 remains an implementation Candidate only. Software Freeze is NOT authorized until the revised Candidate receives targeted external re-review PASS.

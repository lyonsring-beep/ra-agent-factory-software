from __future__ import annotations

from pathlib import Path

from ra_agent_studio.application.control_contracts import CommandEnvelope
from ra_agent_studio.application.control_plane import StudioControlPlane
from ra_agent_studio.application.studio import StudioService
from tests.support import ContractTestFactoryRuntime, ContractTestRuntimeLauncher, authority_registry


def service(tmp_path: Path) -> StudioService:
    return StudioService(
        db_path=str(tmp_path / "v104.db"),
        authority_registry=authority_registry(),
        factory_runtime=ContractTestFactoryRuntime(),
        runtime_launcher=ContractTestRuntimeLauncher(),
    )


def module_command(
    *,
    command_id: str,
    idempotency_key: str,
    target: str = "v104-r1",
    content: str = "print('same')",
    expected_recovery_epoch: int,
) -> CommandEnvelope:
    return CommandEnvelope(
        command_id=command_id,
        operation_descriptor_id="op:factory:module-revision-create",
        exact_target_ref=target,
        principal_ref="builder",
        workspace_ref="ws",
        idempotency_key=idempotency_key,
        expected_recovery_epoch=expected_recovery_epoch,
        payload={
            "module_id":"v104-m1",
            "name":"V104",
            "content":content,
        },
    )


def test_st2_b03_same_idempotency_key_different_command_id_same_request_replays(tmp_path: Path) -> None:
    s=service(tmp_path)
    cp=StudioControlPlane(s)
    epoch=s.store.recovery_epoch()

    first=cp.execute(module_command(
        command_id="cmd-A",
        idempotency_key="idem-001",
        expected_recovery_epoch=epoch,
    ))
    second=cp.execute(module_command(
        command_id="cmd-B",
        idempotency_key="idem-001",
        expected_recovery_epoch=epoch,
    ))

    assert first.standing == "COMMITTED"
    assert second.standing == "REPLAYED"
    assert second.result_ref == first.result_ref == "v104-r1"
    assert second.payload["original_command_id"] == "cmd-A"
    assert second.payload["idempotency_key"] == "idem-001"

    position=s.store.get_idempotency("idem-001")
    assert position is not None
    assert position["command_id"] == "cmd-A"
    assert position["result_key"] == "v104-r1"
    assert len([m for m in s.store.list("module") if m["revision_id"] == "v104-r1"]) == 1


def test_st2_b03_same_idempotency_key_different_request_conflicting_reuse_fails_closed(tmp_path: Path) -> None:
    s=service(tmp_path)
    cp=StudioControlPlane(s)
    epoch=s.store.recovery_epoch()

    first=cp.execute(module_command(
        command_id="cmd-A",
        idempotency_key="idem-001",
        expected_recovery_epoch=epoch,
    ))
    conflict=cp.execute(module_command(
        command_id="cmd-B",
        idempotency_key="idem-001",
        target="v104-r2",
        content="print('different')",
        expected_recovery_epoch=epoch,
    ))

    assert first.standing == "COMMITTED"
    assert conflict.standing == "REJECTED"
    assert "CONFLICTING_REUSE" in (conflict.rejection_reason or "")
    assert s.store.get_idempotency("idem-001")["result_key"] == "v104-r1"

    # The conflicting request must not create any authority-bearing mutation.
    try:
        s.store.get("module","v104-r2")
    except KeyError:
        pass
    else:
        raise AssertionError("CONFLICTING_REUSE created a second module revision")

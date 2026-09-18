from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from ra_agent_studio.domain.identity import ContentHash, ModuleId, RevisionId
from ra_agent_studio.domain.module import ModuleRevision, ModuleRevisionState
from ra_agent_studio.infra.execution import WindowsNativePythonExecutor


pytestmark=pytest.mark.skipif(os.name != "nt",reason="Windows-native sandbox tests require Windows")


def module(content: str) -> ModuleRevision:
    return ModuleRevision(
        module_id=ModuleId("native-win-m"),
        revision_id=RevisionId("native-win-r"),
        content_hash=ContentHash.from_bytes(content.encode("utf-8")),
        name="Native Windows Sandbox Test",
        content=content,
        author_principal_id="test",
        state=ModuleRevisionState.DRAFT,
    )


def executor() -> WindowsNativePythonExecutor:
    return WindowsNativePythonExecutor(
        python_executable=os.environ["RA_STUDIO_WINDOWS_SANDBOX_PYTHON"],
        firewall_rule_name=os.environ["RA_STUDIO_WINDOWS_SANDBOX_FIREWALL_RULE"],
        timeout_seconds=4.0,
    )


def test_native_windows_executor_runs_exact_module_with_stdin() -> None:
    result=executor().execute(module("import sys\nprint('native:' + sys.stdin.read())\n"),"hello")
    assert result.output_text.strip() == "native:hello"
    assert result.exit_code == 0
    assert result.executor_identity.startswith("controlled-windows-native-python-v1:")
    assert result.termination_reason == "completed"


def test_native_windows_executor_has_no_parent_secret_environment() -> None:
    os.environ["RA_STUDIO_TEST_SECRET"]="must-not-leak"
    result=executor().execute(
        module("import os\nprint(os.environ.get('RA_STUDIO_TEST_SECRET','ABSENT'))\n"),
        "",
    )
    assert result.output_text.strip() == "ABSENT"


def test_native_windows_executor_network_is_blocked() -> None:
    content=(
        "import socket\n"
        "s=socket.socket()\n"
        "s.settimeout(1.0)\n"
        "try:\n"
        "    s.connect(('1.1.1.1',80))\n"
        "except OSError:\n"
        "    print('NETWORK_BLOCKED')\n"
        "else:\n"
        "    print('NETWORK_OPEN')\n"
        "finally:\n"
        "    s.close()\n"
    )
    result=executor().execute(module(content),"")
    assert result.output_text.strip() == "NETWORK_BLOCKED"


def test_native_windows_executor_job_blocks_child_process_creation() -> None:
    content=(
        "import subprocess,sys\n"
        "try:\n"
        "    p=subprocess.run([sys.executable,'-c','print(123)'],capture_output=True,text=True,timeout=2)\n"
        "    print('CHILD_EXIT',p.returncode)\n"
        "except Exception as exc:\n"
        "    print('CHILD_BLOCKED',type(exc).__name__)\n"
    )
    result=executor().execute(module(content),"")
    assert result.output_text.startswith("CHILD_BLOCKED")


def test_native_windows_executor_fails_closed_without_firewall_rule(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RA_STUDIO_WINDOWS_SANDBOX_FIREWALL_RULE","RA Agent Studio Missing Rule")
    with pytest.raises(RuntimeError,match="outbound-block firewall rule"):
        WindowsNativePythonExecutor(
            python_executable=os.environ["RA_STUDIO_WINDOWS_SANDBOX_PYTHON"],
            firewall_rule_name="RA Agent Studio Missing Rule",
        )

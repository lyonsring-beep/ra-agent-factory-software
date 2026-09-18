from __future__ import annotations

import os
from pathlib import Path
import tempfile
import time
import winreg

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
        appcontainer_profile_name=os.environ["RA_STUDIO_WINDOWS_SANDBOX_PROFILE"],
        timeout_seconds=3.0,
    )


def test_native_windows_executor_runs_exact_module_with_stdin() -> None:
    result=executor().execute(module("import sys\nprint('native:' + sys.stdin.read())\n"),"hello")
    assert result.output_text.strip() == "native:hello"
    assert result.exit_code == 0
    assert result.executor_identity.startswith("controlled-windows-appcontainer-python-v2:")
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


def test_native_windows_executor_cannot_read_host_sentinel() -> None:
    with tempfile.TemporaryDirectory(prefix="ra-host-sentinel-") as d:
        sentinel=Path(d)/"secret.txt"
        sentinel.write_text("HOST_SECRET",encoding="utf-8")
        code=(
            "from pathlib import Path\n"
            f"p=Path({str(sentinel)!r})\n"
            "try:\n"
            "    print(p.read_text(encoding='utf-8'))\n"
            "except OSError:\n"
            "    print('HOST_READ_DENIED')\n"
        )
        result=executor().execute(module(code),"")
        assert result.output_text.strip() == "HOST_READ_DENIED"


def test_native_windows_executor_cannot_modify_host_sentinel() -> None:
    with tempfile.TemporaryDirectory(prefix="ra-host-sentinel-") as d:
        sentinel=Path(d)/"outside.txt"
        sentinel.write_text("ORIGINAL",encoding="utf-8")
        code=(
            "from pathlib import Path\n"
            f"p=Path({str(sentinel)!r})\n"
            "try:\n"
            "    p.write_text('MUTATED',encoding='utf-8')\n"
            "except OSError:\n"
            "    print('HOST_WRITE_DENIED')\n"
            "else:\n"
            "    print('HOST_WRITE_ALLOWED')\n"
        )
        result=executor().execute(module(code),"")
        assert result.output_text.strip() == "HOST_WRITE_DENIED"
        assert sentinel.read_text(encoding="utf-8") == "ORIGINAL"


def test_native_windows_executor_registry_outside_sandbox_is_denied() -> None:
    key_path=r"Software\RAAgentStudioV106HostSentinel"
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER,key_path) as key:
        winreg.SetValueEx(key,"Secret",0,winreg.REG_SZ,"HOST_REGISTRY_SECRET")
    try:
        code=(
            "import winreg\n"
            f"path={key_path!r}\n"
            "try:\n"
            "    with winreg.OpenKey(winreg.HKEY_CURRENT_USER,path,0,winreg.KEY_READ|winreg.KEY_WRITE) as k:\n"
            "        v=winreg.QueryValueEx(k,'Secret')[0]\n"
            "        winreg.SetValueEx(k,'Secret',0,winreg.REG_SZ,'MUTATED')\n"
            "        print('REGISTRY_ALLOWED',v)\n"
            "except OSError:\n"
            "    print('REGISTRY_DENIED')\n"
        )
        result=executor().execute(module(code),"")
        assert result.output_text.strip() == "REGISTRY_DENIED"
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,key_path) as key:
            assert winreg.QueryValueEx(key,"Secret")[0] == "HOST_REGISTRY_SECRET"
    finally:
        try:
            winreg.DeleteKey(winreg.HKEY_CURRENT_USER,key_path)
        except OSError:
            pass


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


def test_native_windows_process_is_suspended_until_job_attached(monkeypatch: pytest.MonkeyPatch) -> None:
    observed={"suspend_count":None}
    original=WindowsNativePythonExecutor._create_job

    def checked(process_handle: int, thread_handle: int | None = None):
        assert thread_handle is not None
        import ctypes
        from ctypes import wintypes
        kernel32=ctypes.WinDLL("kernel32",use_last_error=True)
        kernel32.SuspendThread.argtypes=[wintypes.HANDLE]
        kernel32.SuspendThread.restype=wintypes.DWORD
        kernel32.ResumeThread.argtypes=[wintypes.HANDLE]
        kernel32.ResumeThread.restype=wintypes.DWORD
        previous=kernel32.SuspendThread(wintypes.HANDLE(thread_handle))
        assert previous != 0xFFFFFFFF
        observed["suspend_count"]=int(previous)
        restored=kernel32.ResumeThread(wintypes.HANDLE(thread_handle))
        assert restored != 0xFFFFFFFF
        time.sleep(0.15)
        return original(process_handle,thread_handle)

    monkeypatch.setattr(WindowsNativePythonExecutor,"_create_job",staticmethod(checked))
    result=executor().execute(module("print('CONTAINED_START')\n"),"")
    assert result.output_text.strip() == "CONTAINED_START"
    assert observed["suspend_count"] >= 1


def test_native_windows_timeout_kills_contained_process() -> None:
    e=WindowsNativePythonExecutor(
        python_executable=os.environ["RA_STUDIO_WINDOWS_SANDBOX_PYTHON"],
        appcontainer_profile_name=os.environ["RA_STUDIO_WINDOWS_SANDBOX_PROFILE"],
        timeout_seconds=0.5,
    )
    with pytest.raises(TimeoutError):
        e.execute(module("while True:\n    pass\n"),"")


def test_native_windows_executor_fails_closed_when_runtime_acl_missing(tmp_path: Path) -> None:
    fake=tmp_path/"python.exe"
    fake.write_bytes(b"MZ")
    with pytest.raises(RuntimeError,match="not ACL-brokered"):
        WindowsNativePythonExecutor(
            python_executable=str(fake),
            appcontainer_profile_name=os.environ["RA_STUDIO_WINDOWS_SANDBOX_PROFILE"],
        )

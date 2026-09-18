from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
from typing import Protocol
from uuid import uuid4

from ra_agent_studio.domain.module import ModuleRevision


@dataclass(frozen=True, slots=True)
class ExecutionResult:
    output_text: str
    stderr_text: str
    exit_code: int
    duration_ms: int
    executor_identity: str
    environment_identity: str
    execution_policy_identity: str
    termination_reason: str


class ControlledExecutor(Protocol):
    def execute(self, revision: ModuleRevision, input_text: str) -> ExecutionResult: ...


class IsolatedPythonProcessExecutor:
    """Fail-closed OCI controlled execution boundary for mutable module code."""

    image = os.environ.get("RA_STUDIO_SANDBOX_IMAGE", "python:3.14-slim")
    policy = {
        "network": "none",
        "rootfs": "read-only",
        "capabilities": "drop-all",
        "no_new_privileges": True,
        "pids_limit": 64,
        "memory": "128m",
        "cpus": "0.5",
        "tmpfs": "/tmp:rw,noexec,nosuid,nodev,size=16m",
        "host_mounts": "exact-module-source-read-only-only",
        "secret_exposure": "none",
        "tool_access": "container-image-only",
    }

    def __init__(self, *, timeout_seconds: float = 5.0, runtime: str | None = None) -> None:
        self.timeout_seconds = timeout_seconds
        self.runtime = runtime or os.environ.get("RA_STUDIO_SANDBOX_RUNTIME") or self._detect_runtime()
        if not self.runtime:
            raise RuntimeError("controlled execution unavailable: docker/podman required; unsafe host fallback is disabled")
        canonical=json.dumps(self.policy,sort_keys=True,separators=(",",":")).encode()
        self.execution_policy_identity=sha256(canonical).hexdigest()
        self.environment_identity=sha256(f"{self.runtime}|{self.image}".encode()).hexdigest()
        self.identity=f"controlled-oci-python-v2:{self.environment_identity[:16]}:{self.execution_policy_identity[:16]}"
        self._ensure_image()

    def _ensure_image(self) -> None:
        inspect = subprocess.run(
            [self.runtime, "image", "inspect", self.image],
            capture_output=True, text=True, env={"PATH": os.environ.get("PATH", "")}, check=False,
        )
        if inspect.returncode == 0:
            return
        pulled = subprocess.run(
            [self.runtime, "pull", self.image],
            capture_output=True, text=True, timeout=180,
            env={"PATH": os.environ.get("PATH", "")}, check=False,
        )
        if pulled.returncode != 0:
            raise RuntimeError(f"controlled execution image unavailable: {pulled.stderr.strip()}")

    @staticmethod
    def _detect_runtime() -> str | None:
        for command in ("docker", "podman"):
            if shutil.which(command):
                return command
        return None

    def execute(self, revision: ModuleRevision, input_text: str) -> ExecutionResult:
        with tempfile.TemporaryDirectory(prefix="ra-studio-controlled-") as temp_dir:
            script=Path(temp_dir)/"module.py"
            script.write_text(revision.content,encoding="utf-8")
            container_name=f"ra-studio-sandbox-{uuid4().hex[:16]}"
            cmd=[
                self.runtime,"run","--rm","-i","--name",container_name,
                "--network","none","--read-only","--cap-drop","ALL",
                "--security-opt","no-new-privileges","--pids-limit","64",
                "--memory","128m","--cpus","0.5",
                "--tmpfs","/tmp:rw,noexec,nosuid,nodev,size=16m",
                "--user","65532:65532",
                "-v",f"{script.resolve()}:/sandbox/module.py:ro",
                self.image,"python","-I","/sandbox/module.py",
            ]
            started=time.monotonic()
            try:
                completed=subprocess.run(
                    cmd,input=input_text,text=True,capture_output=True,
                    timeout=self.timeout_seconds,env={"PATH":os.environ.get("PATH","")},
                    check=False,
                )
                reason="completed"
            except subprocess.TimeoutExpired as exc:
                subprocess.run([self.runtime,"rm","-f",container_name],capture_output=True,text=True,check=False)
                raise TimeoutError(f"controlled execution timeout after {self.timeout_seconds}s") from exc
            duration_ms=int((time.monotonic()-started)*1000)
        if completed.returncode != 0:
            raise RuntimeError(
                f"controlled module execution failed with exit code {completed.returncode}: {completed.stderr.strip()}"
            )
        return ExecutionResult(
            output_text=completed.stdout,stderr_text=completed.stderr,exit_code=completed.returncode,
            duration_ms=duration_ms,executor_identity=self.identity,
            environment_identity=self.environment_identity,
            execution_policy_identity=self.execution_policy_identity,
            termination_reason=reason,
        )


class _JOBOBJECT_BASIC_LIMIT_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("PerProcessUserTimeLimit", ctypes.c_int64),
        ("PerJobUserTimeLimit", ctypes.c_int64),
        ("LimitFlags", wintypes.DWORD),
        ("MinimumWorkingSetSize", ctypes.c_size_t),
        ("MaximumWorkingSetSize", ctypes.c_size_t),
        ("ActiveProcessLimit", wintypes.DWORD),
        ("Affinity", ctypes.c_size_t),
        ("PriorityClass", wintypes.DWORD),
        ("SchedulingClass", wintypes.DWORD),
    ]


class _IO_COUNTERS(ctypes.Structure):
    _fields_ = [
        ("ReadOperationCount", ctypes.c_uint64),
        ("WriteOperationCount", ctypes.c_uint64),
        ("OtherOperationCount", ctypes.c_uint64),
        ("ReadTransferCount", ctypes.c_uint64),
        ("WriteTransferCount", ctypes.c_uint64),
        ("OtherTransferCount", ctypes.c_uint64),
    ]


class _JOBOBJECT_EXTENDED_LIMIT_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("BasicLimitInformation", _JOBOBJECT_BASIC_LIMIT_INFORMATION),
        ("IoInfo", _IO_COUNTERS),
        ("ProcessMemoryLimit", ctypes.c_size_t),
        ("JobMemoryLimit", ctypes.c_size_t),
        ("PeakProcessMemoryUsed", ctypes.c_size_t),
        ("PeakJobMemoryUsed", ctypes.c_size_t),
    ]


class WindowsNativePythonExecutor:
    """Windows-native controlled execution boundary.

    Security model:
    - a dedicated interpreter path configured by the trusted installer;
    - Windows Firewall outbound block is required and verified before every execution;
    - a Windows Job Object limits the sandbox to one active process and 128 MiB;
    - no parent environment or secrets are inherited;
    - the module source is written into a disposable directory and marked read-only;
    - isolated Python mode (-I) and no site import (-S) reduce ambient code loading;
    - timeout terminates the entire Job Object.

    This is a separate, explicit provider. It never silently falls back from OCI.
    """

    JOB_OBJECT_LIMIT_ACTIVE_PROCESS = 0x00000008
    JOB_OBJECT_LIMIT_PROCESS_MEMORY = 0x00000100
    JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000
    JobObjectExtendedLimitInformation = 9

    policy = {
        "network": "windows-firewall-outbound-block-required",
        "filesystem": "disposable-workdir-plus-read-only-module-source",
        "process_tree": "windows-job-object-active-process-limit-1",
        "memory": "128m-process-limit",
        "python": "isolated-mode-no-site",
        "environment": "allowlist-only-no-parent-secrets",
        "timeout": "job-object-termination",
        "host_fallback": "none",
    }

    def __init__(
        self,
        *,
        timeout_seconds: float = 5.0,
        python_executable: str | None = None,
        firewall_rule_name: str | None = None,
    ) -> None:
        if os.name != "nt":
            raise RuntimeError("Windows native controlled execution is only available on Windows")
        self.timeout_seconds=timeout_seconds
        self.python_executable=str(Path(
            python_executable or os.environ.get("RA_STUDIO_WINDOWS_SANDBOX_PYTHON","")
        ).resolve())
        if not self.python_executable or not Path(self.python_executable).is_file():
            raise RuntimeError("RA_STUDIO_WINDOWS_SANDBOX_PYTHON must name the dedicated sandbox interpreter")
        self.firewall_rule_name=(
            firewall_rule_name
            or os.environ.get("RA_STUDIO_WINDOWS_SANDBOX_FIREWALL_RULE","RA Agent Studio v1.06 Sandbox No Network")
        )
        self._verify_firewall_guard()
        canonical=json.dumps(self.policy,sort_keys=True,separators=(",",":")).encode()
        self.execution_policy_identity=sha256(canonical).hexdigest()
        self.environment_identity=sha256(
            f"windows-native|{self.python_executable}|{sys.version_info.major}.{sys.version_info.minor}".encode()
        ).hexdigest()
        self.identity=f"controlled-windows-native-python-v1:{self.environment_identity[:16]}:{self.execution_policy_identity[:16]}"

    def _verify_firewall_guard(self) -> None:
        escaped_rule=self.firewall_rule_name.replace("'","''")
        escaped_program=self.python_executable.replace("'","''")
        command=(
            "$ErrorActionPreference='Stop';"
            "$policy=New-Object -ComObject HNetCfg.FwPolicy2;"
            f"$rule=$policy.Rules.Item('{escaped_rule}');"
            "if(-not $rule){exit 11};"
            "if(-not $rule.Enabled -or $rule.Direction -ne 2 -or $rule.Action -ne 0){exit 12};"
            f"if([IO.Path]::GetFullPath($rule.ApplicationName) -ne [IO.Path]::GetFullPath('{escaped_program}')){{exit 13}}"
        )
        try:
            checked=subprocess.run(
                ["powershell.exe","-NoProfile","-NonInteractive","-Command",command],
                capture_output=True,text=True,check=False,timeout=20,
                env={"SystemRoot":os.environ.get("SystemRoot",r"C:\\Windows"),"PATH":os.environ.get("PATH","")},
            )
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError("Windows native firewall guard verification timed out") from exc
        if checked.returncode != 0:
            raise RuntimeError(
                "Windows native controlled execution requires an enabled outbound-block firewall rule "
                "bound to the dedicated sandbox interpreter"
            )

    @staticmethod
    def _create_job(process_handle: int):
        kernel32=ctypes.WinDLL("kernel32",use_last_error=True)
        kernel32.CreateJobObjectW.argtypes=[ctypes.c_void_p,wintypes.LPCWSTR]
        kernel32.CreateJobObjectW.restype=wintypes.HANDLE
        kernel32.SetInformationJobObject.argtypes=[wintypes.HANDLE,ctypes.c_int,ctypes.c_void_p,wintypes.DWORD]
        kernel32.SetInformationJobObject.restype=wintypes.BOOL
        kernel32.AssignProcessToJobObject.argtypes=[wintypes.HANDLE,wintypes.HANDLE]
        kernel32.AssignProcessToJobObject.restype=wintypes.BOOL

        job=kernel32.CreateJobObjectW(None,None)
        if not job:
            raise ctypes.WinError(ctypes.get_last_error())

        info=_JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
        info.BasicLimitInformation.LimitFlags=(
            WindowsNativePythonExecutor.JOB_OBJECT_LIMIT_ACTIVE_PROCESS
            | WindowsNativePythonExecutor.JOB_OBJECT_LIMIT_PROCESS_MEMORY
            | WindowsNativePythonExecutor.JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        )
        info.BasicLimitInformation.ActiveProcessLimit=1
        info.ProcessMemoryLimit=128*1024*1024

        if not kernel32.SetInformationJobObject(
            job,
            WindowsNativePythonExecutor.JobObjectExtendedLimitInformation,
            ctypes.byref(info),
            ctypes.sizeof(info),
        ):
            err=ctypes.get_last_error()
            kernel32.CloseHandle(job)
            raise ctypes.WinError(err)

        if not kernel32.AssignProcessToJobObject(job,wintypes.HANDLE(process_handle)):
            err=ctypes.get_last_error()
            kernel32.CloseHandle(job)
            raise ctypes.WinError(err)
        return job,kernel32

    def execute(self, revision: ModuleRevision, input_text: str) -> ExecutionResult:
        self._verify_firewall_guard()
        with tempfile.TemporaryDirectory(prefix="ra-studio-windows-controlled-") as temp_dir:
            root=Path(temp_dir)
            script=root/"module.py"
            script.write_text(revision.content,encoding="utf-8")
            script.chmod(0o444)
            scratch=root/"tmp"
            scratch.mkdir()
            env={
                "SystemRoot":os.environ.get("SystemRoot",r"C:\Windows"),
                "WINDIR":os.environ.get("WINDIR",r"C:\Windows"),
                "TEMP":str(scratch),
                "TMP":str(scratch),
                "PYTHONIOENCODING":"utf-8",
                "PYTHONUTF8":"1",
            }
            creationflags=getattr(subprocess,"CREATE_NO_WINDOW",0)
            started=time.monotonic()
            process=subprocess.Popen(
                [self.python_executable,"-I","-S",str(script)],
                stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,
                text=True,cwd=str(root),env=env,creationflags=creationflags,
            )
            job=None
            kernel32=None
            try:
                job,kernel32=self._create_job(int(process._handle))
                try:
                    stdout,stderr=process.communicate(input=input_text,timeout=self.timeout_seconds)
                    reason="completed"
                except subprocess.TimeoutExpired as exc:
                    if kernel32 and job:
                        kernel32.TerminateJobObject(job,1460)
                    process.kill()
                    process.wait(timeout=5)
                    raise TimeoutError(f"controlled execution timeout after {self.timeout_seconds}s") from exc
            finally:
                if kernel32 and job:
                    kernel32.CloseHandle(job)
            duration_ms=int((time.monotonic()-started)*1000)

        if process.returncode != 0:
            raise RuntimeError(
                f"controlled module execution failed with exit code {process.returncode}: {stderr.strip()}"
            )
        return ExecutionResult(
            output_text=stdout,stderr_text=stderr,exit_code=process.returncode,
            duration_ms=duration_ms,executor_identity=self.identity,
            environment_identity=self.environment_identity,
            execution_policy_identity=self.execution_policy_identity,
            termination_reason=reason,
        )


def default_controlled_executor() -> ControlledExecutor:
    provider=os.environ.get("RA_STUDIO_CONTROLLED_EXECUTION_PROVIDER","").strip().lower()
    if provider == "windows-native":
        return WindowsNativePythonExecutor()
    if provider in {"","oci"}:
        return IsolatedPythonProcessExecutor()
    raise RuntimeError(f"unsupported controlled execution provider: {provider}")

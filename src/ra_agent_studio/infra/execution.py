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


class _SID_AND_ATTRIBUTES(ctypes.Structure):
    _fields_ = [("Sid", ctypes.c_void_p), ("Attributes", wintypes.DWORD)]


class _SECURITY_CAPABILITIES(ctypes.Structure):
    _fields_ = [
        ("AppContainerSid", ctypes.c_void_p),
        ("Capabilities", ctypes.POINTER(_SID_AND_ATTRIBUTES)),
        ("CapabilityCount", wintypes.DWORD),
        ("Reserved", wintypes.DWORD),
    ]


class _STARTUPINFOW(ctypes.Structure):
    _fields_ = [
        ("cb", wintypes.DWORD),
        ("lpReserved", wintypes.LPWSTR),
        ("lpDesktop", wintypes.LPWSTR),
        ("lpTitle", wintypes.LPWSTR),
        ("dwX", wintypes.DWORD),
        ("dwY", wintypes.DWORD),
        ("dwXSize", wintypes.DWORD),
        ("dwYSize", wintypes.DWORD),
        ("dwXCountChars", wintypes.DWORD),
        ("dwYCountChars", wintypes.DWORD),
        ("dwFillAttribute", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("wShowWindow", wintypes.WORD),
        ("cbReserved2", wintypes.WORD),
        ("lpReserved2", ctypes.POINTER(ctypes.c_ubyte)),
        ("hStdInput", wintypes.HANDLE),
        ("hStdOutput", wintypes.HANDLE),
        ("hStdError", wintypes.HANDLE),
    ]


class _STARTUPINFOEXW(ctypes.Structure):
    _fields_ = [("StartupInfo", _STARTUPINFOW), ("lpAttributeList", ctypes.c_void_p)]


class _PROCESS_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("hProcess", wintypes.HANDLE),
        ("hThread", wintypes.HANDLE),
        ("dwProcessId", wintypes.DWORD),
        ("dwThreadId", wintypes.DWORD),
    ]


class WindowsNativePythonExecutor:
    """Windows-native controlled execution boundary using AppContainer + Job Objects.

    The module process is created inside a no-capability AppContainer in CREATE_SUSPENDED
    state. The Job Object is fully configured and attached before the primary thread is
    resumed. The AppContainer removes ambient same-user filesystem/registry authority;
    only the dedicated Python runtime (RX) and the disposable sandbox directory (M) are
    explicitly ACL-brokered. With no network capability, outbound networking is denied.

    Any profile, ACL, process-creation, attribute-list, Job assignment, or resume failure
    terminates/cleans up and fails closed. There is no unsafe host-subprocess fallback.
    """

    JOB_OBJECT_LIMIT_ACTIVE_PROCESS = 0x00000008
    JOB_OBJECT_LIMIT_PROCESS_MEMORY = 0x00000100
    JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000
    JobObjectExtendedLimitInformation = 9

    CREATE_SUSPENDED = 0x00000004
    CREATE_NO_WINDOW = 0x08000000
    CREATE_UNICODE_ENVIRONMENT = 0x00000400
    EXTENDED_STARTUPINFO_PRESENT = 0x00080000
    PROC_THREAD_ATTRIBUTE_SECURITY_CAPABILITIES = 0x00020009
    ERROR_ALREADY_EXISTS = 183
    WAIT_OBJECT_0 = 0
    WAIT_TIMEOUT = 258
    INFINITE = 0xFFFFFFFF

    policy = {
        "network": "appcontainer-no-network-capability",
        "host_resources": "appcontainer-default-deny",
        "filesystem": "runtime-rx-plus-disposable-sandbox-only",
        "registry": "appcontainer-isolated-default-deny",
        "process_tree": "windows-job-object-active-process-limit-1",
        "startup_order": "create-suspended-appcontainer-attach-job-resume",
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
        appcontainer_profile_name: str | None = None,
    ) -> None:
        if os.name != "nt":
            raise RuntimeError("Windows native controlled execution is only available on Windows")
        self.timeout_seconds=timeout_seconds
        configured=python_executable or os.environ.get("RA_STUDIO_WINDOWS_SANDBOX_PYTHON","")
        if not configured:
            raise RuntimeError("RA_STUDIO_WINDOWS_SANDBOX_PYTHON must name the dedicated sandbox interpreter")
        self.python_executable=str(Path(configured).resolve())
        if not Path(self.python_executable).is_file():
            raise RuntimeError("RA_STUDIO_WINDOWS_SANDBOX_PYTHON must name the dedicated sandbox interpreter")
        self.python_root=str(Path(self.python_executable).parent.resolve())
        self.appcontainer_profile_name=(
            appcontainer_profile_name
            or os.environ.get("RA_STUDIO_WINDOWS_SANDBOX_PROFILE","RAAgentStudio.Sandbox.v106")
        )
        self._appcontainer_sid,self._appcontainer_sid_string=self._ensure_appcontainer_profile()
        self._verify_runtime_acl()
        canonical=json.dumps(self.policy,sort_keys=True,separators=(",",":")).encode()
        self.execution_policy_identity=sha256(canonical).hexdigest()
        self.environment_identity=sha256(
            f"windows-appcontainer|{self.python_executable}|{self._appcontainer_sid_string}|"
            f"{sys.version_info.major}.{sys.version_info.minor}".encode()
        ).hexdigest()
        self.identity=f"controlled-windows-appcontainer-python-v2:{self.environment_identity[:16]}:{self.execution_policy_identity[:16]}"

    @staticmethod
    def _hr_code(value: int) -> int:
        return ctypes.c_uint32(value).value

    def _ensure_appcontainer_profile(self) -> tuple[ctypes.c_void_p,str]:
        userenv=ctypes.WinDLL("userenv",use_last_error=True)
        advapi32=ctypes.WinDLL("advapi32",use_last_error=True)
        kernel32=ctypes.WinDLL("kernel32",use_last_error=True)

        userenv.CreateAppContainerProfile.argtypes=[
            wintypes.LPCWSTR,wintypes.LPCWSTR,wintypes.LPCWSTR,
            ctypes.POINTER(_SID_AND_ATTRIBUTES),wintypes.DWORD,ctypes.POINTER(ctypes.c_void_p),
        ]
        userenv.CreateAppContainerProfile.restype=ctypes.c_long
        userenv.DeriveAppContainerSidFromAppContainerName.argtypes=[
            wintypes.LPCWSTR,ctypes.POINTER(ctypes.c_void_p)
        ]
        userenv.DeriveAppContainerSidFromAppContainerName.restype=ctypes.c_long
        advapi32.ConvertSidToStringSidW.argtypes=[ctypes.c_void_p,ctypes.POINTER(wintypes.LPWSTR)]
        advapi32.ConvertSidToStringSidW.restype=wintypes.BOOL
        kernel32.LocalFree.argtypes=[wintypes.HLOCAL]
        kernel32.LocalFree.restype=wintypes.HLOCAL

        sid=ctypes.c_void_p()
        hr=userenv.CreateAppContainerProfile(
            self.appcontainer_profile_name,
            "RA Agent Studio Sandbox",
            "RA Agent Studio v1.06 controlled execution sandbox",
            None,0,ctypes.byref(sid),
        )
        code=self._hr_code(hr)
        if code == (0x80070000 | self.ERROR_ALREADY_EXISTS):
            sid=ctypes.c_void_p()
            hr=userenv.DeriveAppContainerSidFromAppContainerName(
                self.appcontainer_profile_name,ctypes.byref(sid)
            )
            if self._hr_code(hr) != 0:
                raise RuntimeError(f"failed to derive AppContainer SID: HRESULT 0x{self._hr_code(hr):08x}")
        elif code != 0:
            raise RuntimeError(f"failed to create AppContainer profile: HRESULT 0x{code:08x}")

        text=wintypes.LPWSTR()
        if not advapi32.ConvertSidToStringSidW(sid,ctypes.byref(text)):
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            sid_string=text.value
        finally:
            kernel32.LocalFree(text)
        if not sid_string:
            raise RuntimeError("AppContainer SID string is empty")
        return sid,sid_string

    def _verify_runtime_acl(self) -> None:
        """Verify the dedicated runtime directory explicitly brokers AppContainer RX access."""
        checked=subprocess.run(
            ["icacls",self.python_root],
            capture_output=True,text=True,check=False,timeout=20,
            env=os.environ.copy(),
        )
        if checked.returncode != 0 or self._appcontainer_sid_string.lower() not in checked.stdout.lower():
            raise RuntimeError(
                "dedicated sandbox Python runtime is not ACL-brokered to the AppContainer SID"
            )

    def _grant_sandbox_acl(self, root: Path) -> None:
        grant=f"*{self._appcontainer_sid_string}:(OI)(CI)(M)"
        result=subprocess.run(
            ["icacls",str(root),"/inheritance:r","/grant:r",grant],
            capture_output=True,text=True,check=False,timeout=20,
            env=os.environ.copy(),
        )
        if result.returncode != 0:
            raise RuntimeError(f"failed to ACL-broker sandbox directory: {result.stderr.strip() or result.stdout.strip()}")

    @staticmethod
    def _create_job(process_handle: int):
        kernel32=ctypes.WinDLL("kernel32",use_last_error=True)
        kernel32.CreateJobObjectW.argtypes=[ctypes.c_void_p,wintypes.LPCWSTR]
        kernel32.CreateJobObjectW.restype=wintypes.HANDLE
        kernel32.SetInformationJobObject.argtypes=[wintypes.HANDLE,ctypes.c_int,ctypes.c_void_p,wintypes.DWORD]
        kernel32.SetInformationJobObject.restype=wintypes.BOOL
        kernel32.AssignProcessToJobObject.argtypes=[wintypes.HANDLE,wintypes.HANDLE]
        kernel32.AssignProcessToJobObject.restype=wintypes.BOOL
        kernel32.TerminateJobObject.argtypes=[wintypes.HANDLE,wintypes.UINT]
        kernel32.TerminateJobObject.restype=wintypes.BOOL
        kernel32.CloseHandle.argtypes=[wintypes.HANDLE]
        kernel32.CloseHandle.restype=wintypes.BOOL

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
            job,WindowsNativePythonExecutor.JobObjectExtendedLimitInformation,
            ctypes.byref(info),ctypes.sizeof(info),
        ):
            err=ctypes.get_last_error()
            kernel32.CloseHandle(job)
            raise ctypes.WinError(err)
        if not kernel32.AssignProcessToJobObject(job,wintypes.HANDLE(process_handle)):
            err=ctypes.get_last_error()
            kernel32.CloseHandle(job)
            raise ctypes.WinError(err)
        return job,kernel32

    def _create_suspended_appcontainer_process(
        self, *, command: list[str], cwd: str, env: dict[str,str],
    ) -> tuple[_PROCESS_INFORMATION,ctypes.Array]:
        kernel32=ctypes.WinDLL("kernel32",use_last_error=True)
        kernel32.InitializeProcThreadAttributeList.argtypes=[
            ctypes.c_void_p,wintypes.DWORD,wintypes.DWORD,ctypes.POINTER(ctypes.c_size_t)
        ]
        kernel32.InitializeProcThreadAttributeList.restype=wintypes.BOOL
        kernel32.UpdateProcThreadAttribute.argtypes=[
            ctypes.c_void_p,wintypes.DWORD,ctypes.c_size_t,ctypes.c_void_p,
            ctypes.c_size_t,ctypes.c_void_p,ctypes.c_void_p,
        ]
        kernel32.UpdateProcThreadAttribute.restype=wintypes.BOOL
        kernel32.DeleteProcThreadAttributeList.argtypes=[ctypes.c_void_p]
        kernel32.DeleteProcThreadAttributeList.restype=None
        kernel32.CreateProcessW.argtypes=[
            wintypes.LPCWSTR,wintypes.LPWSTR,ctypes.c_void_p,ctypes.c_void_p,wintypes.BOOL,
            wintypes.DWORD,ctypes.c_void_p,wintypes.LPCWSTR,
            ctypes.POINTER(_STARTUPINFOW),ctypes.POINTER(_PROCESS_INFORMATION),
        ]
        kernel32.CreateProcessW.restype=wintypes.BOOL

        size=ctypes.c_size_t(0)
        kernel32.InitializeProcThreadAttributeList(None,1,0,ctypes.byref(size))
        buffer=ctypes.create_string_buffer(size.value)
        attr=ctypes.cast(buffer,ctypes.c_void_p)
        if not kernel32.InitializeProcThreadAttributeList(attr,1,0,ctypes.byref(size)):
            raise ctypes.WinError(ctypes.get_last_error())

        capabilities=_SECURITY_CAPABILITIES(
            AppContainerSid=self._appcontainer_sid,
            Capabilities=None,
            CapabilityCount=0,
            Reserved=0,
        )
        if not kernel32.UpdateProcThreadAttribute(
            attr,0,self.PROC_THREAD_ATTRIBUTE_SECURITY_CAPABILITIES,
            ctypes.byref(capabilities),ctypes.sizeof(capabilities),None,None,
        ):
            kernel32.DeleteProcThreadAttributeList(attr)
            raise ctypes.WinError(ctypes.get_last_error())

        startup=_STARTUPINFOEXW()
        startup.StartupInfo.cb=ctypes.sizeof(_STARTUPINFOEXW)
        startup.lpAttributeList=attr
        pi=_PROCESS_INFORMATION()
        cmdline=ctypes.create_unicode_buffer(subprocess.list2cmdline(command))
        env_block=ctypes.create_unicode_buffer(
            "\0".join(f"{k}={v}" for k,v in sorted(env.items(),key=lambda x:x[0].upper()))+"\0\0"
        )
        flags=(
            self.CREATE_SUSPENDED
            | self.CREATE_NO_WINDOW
            | self.CREATE_UNICODE_ENVIRONMENT
            | self.EXTENDED_STARTUPINFO_PRESENT
        )
        ok=kernel32.CreateProcessW(
            self.python_executable,cmdline,None,None,False,flags,
            ctypes.cast(env_block,ctypes.c_void_p),cwd,
            ctypes.byref(startup.StartupInfo),ctypes.byref(pi),
        )
        kernel32.DeleteProcThreadAttributeList(attr)
        if not ok:
            raise ctypes.WinError(ctypes.get_last_error())
        return pi,buffer

    def execute(self, revision: ModuleRevision, input_text: str) -> ExecutionResult:
        with tempfile.TemporaryDirectory(prefix="ra-studio-windows-appcontainer-") as temp_dir:
            root=Path(temp_dir)
            self._grant_sandbox_acl(root)

            script=root/"module.py"
            input_path=root/"input.txt"
            stdout_path=root/"stdout.txt"
            stderr_path=root/"stderr.txt"
            runner=root/"runner.py"
            script.write_text(revision.content,encoding="utf-8")
            input_path.write_text(input_text,encoding="utf-8")
            stdout_path.write_text("",encoding="utf-8")
            stderr_path.write_text("",encoding="utf-8")
            runner.write_text(
                "import io, pathlib, sys, traceback\n"
                "root=pathlib.Path(__file__).resolve().parent\n"
                "stdin_text=(root/'input.txt').read_text(encoding='utf-8')\n"
                "out=(root/'stdout.txt').open('w',encoding='utf-8')\n"
                "err=(root/'stderr.txt').open('w',encoding='utf-8')\n"
                "sys.stdin=io.StringIO(stdin_text); sys.stdout=out; sys.stderr=err\n"
                "try:\n"
                "    source=(root/'module.py').read_text(encoding='utf-8')\n"
                "    exec(compile(source,str(root/'module.py'),'exec'),{'__name__':'__main__','__file__':str(root/'module.py')})\n"
                "except BaseException:\n"
                "    traceback.print_exc(file=err); out.flush(); err.flush(); raise\n"
                "finally:\n"
                "    out.flush(); err.flush(); out.close(); err.close()\n",
                encoding="utf-8",
            )
            script.chmod(0o444)
            input_path.chmod(0o444)
            runner.chmod(0o444)

            env={
                "SystemRoot":os.environ.get("SystemRoot",r"C:\Windows"),
                "WINDIR":os.environ.get("WINDIR",r"C:\Windows"),
                "TEMP":str(root),
                "TMP":str(root),
                "PYTHONIOENCODING":"utf-8",
                "PYTHONUTF8":"1",
            }
            started=time.monotonic()
            pi=None
            job=None
            kernel32=None
            resumed=False
            try:
                pi,_attr_buffer=self._create_suspended_appcontainer_process(
                    command=[self.python_executable,"-I","-S",str(runner)],
                    cwd=str(root),env=env,
                )
                try:
                    job,kernel32=self._create_job(int(pi.hProcess))
                except BaseException:
                    ctypes.WinDLL("kernel32",use_last_error=True).TerminateProcess(pi.hProcess,126)
                    raise

                resume=kernel32.ResumeThread
                resume.argtypes=[wintypes.HANDLE]
                resume.restype=wintypes.DWORD
                previous=resume(pi.hThread)
                if previous == 0xFFFFFFFF:
                    kernel32.TerminateJobObject(job,127)
                    raise ctypes.WinError(ctypes.get_last_error())
                resumed=True

                wait=kernel32.WaitForSingleObject
                wait.argtypes=[wintypes.HANDLE,wintypes.DWORD]
                wait.restype=wintypes.DWORD
                timeout_ms=max(1,int(self.timeout_seconds*1000))
                wait_result=wait(pi.hProcess,timeout_ms)
                if wait_result == self.WAIT_TIMEOUT:
                    kernel32.TerminateJobObject(job,1460)
                    wait(pi.hProcess,5000)
                    raise TimeoutError(f"controlled execution timeout after {self.timeout_seconds}s")
                if wait_result != self.WAIT_OBJECT_0:
                    kernel32.TerminateJobObject(job,128)
                    raise RuntimeError(f"WaitForSingleObject failed with code {wait_result}")

                exit_code=wintypes.DWORD()
                kernel32.GetExitCodeProcess.argtypes=[wintypes.HANDLE,ctypes.POINTER(wintypes.DWORD)]
                kernel32.GetExitCodeProcess.restype=wintypes.BOOL
                if not kernel32.GetExitCodeProcess(pi.hProcess,ctypes.byref(exit_code)):
                    raise ctypes.WinError(ctypes.get_last_error())
                code=int(exit_code.value)
            finally:
                if pi is not None:
                    closer=ctypes.WinDLL("kernel32",use_last_error=True)
                    if not resumed and job:
                        closer.TerminateJobObject(job,129)
                    if pi.hThread:
                        closer.CloseHandle(pi.hThread)
                    if pi.hProcess:
                        closer.CloseHandle(pi.hProcess)
                if kernel32 and job:
                    kernel32.CloseHandle(job)

            duration_ms=int((time.monotonic()-started)*1000)
            stdout=stdout_path.read_text(encoding="utf-8",errors="replace")
            stderr=stderr_path.read_text(encoding="utf-8",errors="replace")

        if code != 0:
            raise RuntimeError(
                f"controlled module execution failed with exit code {code}: {stderr.strip()}"
            )
        return ExecutionResult(
            output_text=stdout,stderr_text=stderr,exit_code=code,
            duration_ms=duration_ms,executor_identity=self.identity,
            environment_identity=self.environment_identity,
            execution_policy_identity=self.execution_policy_identity,
            termination_reason="completed",
        )


def default_controlled_executor() -> ControlledExecutor:
    provider=os.environ.get("RA_STUDIO_CONTROLLED_EXECUTION_PROVIDER","").strip().lower()
    if provider == "windows-native":
        return WindowsNativePythonExecutor()
    if provider in {"","oci"}:
        return IsolatedPythonProcessExecutor()
    raise RuntimeError(f"unsupported controlled execution provider: {provider}")

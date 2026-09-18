from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time
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


class IsolatedPythonProcessExecutor:
    """Fail-closed controlled execution boundary for mutable module code.

    Execution occurs in a disposable OCI container with no network, read-only rootfs,
    dropped Linux capabilities, no-new-privileges, bounded PIDs/memory/CPU, an isolated
    tmpfs and only the exact module source mounted read-only. No host environment or
    secrets are forwarded. If a supported container runtime is unavailable execution
    fails closed rather than silently degrading to a host subprocess.
    """

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

from __future__ import annotations

from dataclasses import dataclass
import json
import os
import shlex
import subprocess
from typing import Protocol


@dataclass(frozen=True, slots=True)
class ExternalRuntimeResult:
    standing: str
    external_runtime_identity: str = ""
    detail: str = ""


class RuntimeLauncher(Protocol):
    def launch(self, *, deployment_id: str, activation_attempt_id: str, realization: dict) -> ExternalRuntimeResult: ...
    def stop(self, *, deployment_id: str, stop_attempt_id: str, external_runtime_identity: str) -> ExternalRuntimeResult: ...


class SubprocessRuntimeLauncher:
    """Production runtime provider adapter.

    Commands are server configuration, never request supplied. The launcher sends a bounded
    JSON request on stdin and requires one JSON result on stdout:
    {"standing":"ACTIVATED|FAILED|AMBIGUOUS","external_runtime_identity":"...","detail":"..."}
    for launch and {"standing":"STOPPED|FAILED|AMBIGUOUS", ...} for stop.
    Missing configuration fails closed.
    """

    def __init__(self, launch_command: list[str], stop_command: list[str], *, timeout_seconds: float = 60.0) -> None:
        if not launch_command or not stop_command:
            raise RuntimeError("runtime launcher commands are required")
        self.launch_command=launch_command
        self.stop_command=stop_command
        self.timeout_seconds=timeout_seconds

    @classmethod
    def from_environment(cls) -> "SubprocessRuntimeLauncher":
        launch=os.environ.get("RA_STUDIO_RUNTIME_LAUNCH_COMMAND","").strip()
        stop=os.environ.get("RA_STUDIO_RUNTIME_STOP_COMMAND","").strip()
        if not launch or not stop:
            raise RuntimeError("production runtime launcher is not configured")
        return cls(shlex.split(launch),shlex.split(stop))

    def _run(self, command: list[str], payload: dict) -> dict:
        try:
            completed=subprocess.run(
                command,
                input=json.dumps(payload,sort_keys=True,separators=(",",":")),
                text=True,capture_output=True,timeout=self.timeout_seconds,check=False,
                env={"PATH":os.environ.get("PATH","")},
            )
        except subprocess.TimeoutExpired as exc:
            return {"standing":"AMBIGUOUS","detail":f"provider timeout after {self.timeout_seconds}s"}
        if completed.returncode != 0:
            return {"standing":"FAILED","detail":completed.stderr.strip() or f"provider exit {completed.returncode}"}
        try:
            data=json.loads(completed.stdout)
        except json.JSONDecodeError:
            return {"standing":"AMBIGUOUS","detail":"provider returned non-JSON result"}
        return data

    def launch(self, *, deployment_id: str, activation_attempt_id: str, realization: dict) -> ExternalRuntimeResult:
        data=self._run(self.launch_command,{
            "operation":"launch","deployment_id":deployment_id,
            "activation_attempt_id":activation_attempt_id,
            "provider_idempotency_key":activation_attempt_id,
            "realization":realization,
        })
        standing=str(data.get("standing","AMBIGUOUS")).upper()
        if standing not in {"ACTIVATED","FAILED","AMBIGUOUS"}:
            standing="AMBIGUOUS"
        identity=str(data.get("external_runtime_identity",""))
        if standing=="ACTIVATED" and not identity:
            return ExternalRuntimeResult("AMBIGUOUS","", "provider claimed ACTIVATED without runtime identity")
        return ExternalRuntimeResult(standing,identity,str(data.get("detail","")))

    def stop(self, *, deployment_id: str, stop_attempt_id: str, external_runtime_identity: str) -> ExternalRuntimeResult:
        data=self._run(self.stop_command,{
            "operation":"stop","deployment_id":deployment_id,
            "stop_attempt_id":stop_attempt_id,
            "provider_idempotency_key":stop_attempt_id,
            "external_runtime_identity":external_runtime_identity,
        })
        standing=str(data.get("standing","AMBIGUOUS")).upper()
        if standing not in {"STOPPED","FAILED","AMBIGUOUS"}:
            standing="AMBIGUOUS"
        return ExternalRuntimeResult(standing,str(data.get("external_runtime_identity",external_runtime_identity)),str(data.get("detail","")))

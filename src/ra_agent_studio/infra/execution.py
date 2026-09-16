from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time

from ra_agent_studio.domain.module import ModuleRevision


@dataclass(frozen=True, slots=True)
class ExecutionResult:
    output_text: str
    stderr_text: str
    exit_code: int
    duration_ms: int
    executor_identity: str


class IsolatedPythonProcessExecutor:
    """Execute the exact module revision as a separate isolated Python process.

    The module receives fixture text on stdin and must write its observable result to stdout.
    This executor is authority-free: execution cannot review, freeze, promote or deploy.
    """

    identity = "isolated-python-process-v1"

    def __init__(self, *, timeout_seconds: float = 5.0) -> None:
        self.timeout_seconds = timeout_seconds

    def execute(self, revision: ModuleRevision, input_text: str) -> ExecutionResult:
        with tempfile.TemporaryDirectory(prefix="ra-studio-sandbox-") as temp_dir:
            script = Path(temp_dir) / "module.py"
            script.write_text(revision.content, encoding="utf-8")
            started = time.monotonic()
            completed = subprocess.run(
                [sys.executable, "-I", str(script)],
                input=input_text,
                text=True,
                capture_output=True,
                cwd=temp_dir,
                timeout=self.timeout_seconds,
                env={"PATH": os.environ.get("PATH", ""), "PYTHONIOENCODING": "utf-8"},
                check=False,
            )
            duration_ms = int((time.monotonic() - started) * 1000)
        if completed.returncode != 0:
            raise RuntimeError(
                f"module execution failed with exit code {completed.returncode}: {completed.stderr.strip()}"
            )
        return ExecutionResult(
            output_text=completed.stdout,
            stderr_text=completed.stderr,
            exit_code=completed.returncode,
            duration_ms=duration_ms,
            executor_identity=self.identity,
        )

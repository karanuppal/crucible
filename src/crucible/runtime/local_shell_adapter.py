"""Phase 8: LocalShellAdapter — runs the spec's verification command in a real shell.

This is the default backend for the standalone CLI. Unlike InMemoryAdapter,
it does NOT rubber-stamp results — it actually executes the command and
returns COMPLETE only if the command exits 0 and stdout matches expectations.

The adapter expects the AdapterRunSpec.prompt to encode the verification
command (the run_executor wires this up from the Criterion triple). For
multi-criterion tasks, the executor invokes the adapter once per criterion
and aggregates.

This adapter is intentionally simple: subprocess.run with timeout, no
sandboxing. Production embedders should use real backends (Codex, Claude
Code, OpenClaw sub-agents) that can actually edit files. LocalShell is
the verification-honest baseline.
"""

from __future__ import annotations

import os
import shlex
import subprocess
import time
import uuid
from dataclasses import dataclass
from typing import Any

from crucible.accelerators.adapters import (
    BackendAdapter, AdapterRunSpec, AdapterRunHandle, AdapterRunResult,
    AdapterStatus,
)
from crucible.accelerators.capabilities import (
    BackendCapabilities, Capability,
)


def default_local_shell_capabilities(backend_id: str = "local-shell") -> BackendCapabilities:
    return BackendCapabilities(
        backend_id=backend_id,
        supports={
            Capability.SHELL_EXEC,
            Capability.FILE_WRITE,
            Capability.LONG_RUNNING,
            Capability.ARTIFACT_PRODUCTION,
        },
        max_concurrent_runs=4,
    )


@dataclass
class _LocalRun:
    handle_id: str
    spec: AdapterRunSpec
    started_at: float
    finished_at: float
    status: AdapterStatus
    stdout: str
    stderr: str
    exit_code: int
    expected_substring: str = ""


class LocalShellAdapter(BackendAdapter):
    """Synchronous shell-execution adapter for local verification.
    
    Honest: a "complete" verdict from this adapter means the verification
    command really exited 0 and (if expected_substring is set) stdout
    really contained the expected substring.
    """
    
    def __init__(
        self,
        *,
        backend_id: str = "local-shell",
        capabilities: BackendCapabilities | None = None,
        default_timeout_seconds: int = 60,
    ) -> None:
        self._backend_id = backend_id
        self._caps = capabilities or default_local_shell_capabilities(backend_id)
        self._default_timeout = default_timeout_seconds
        self._runs: dict[str, _LocalRun] = {}
    
    def backend_id(self) -> str:
        return self._backend_id
    
    def declared_capabilities(self) -> BackendCapabilities:
        return self._caps
    
    def spawn(self, spec: AdapterRunSpec) -> AdapterRunHandle:
        if not self._caps.supports_all(spec.required_capabilities):
            missing = spec.required_capabilities - self._caps.supports
            raise ValueError(
                f"LocalShellAdapter does not support: {sorted(c.value for c in missing)}"
            )
        
        handle_id = f"{self._backend_id}-{uuid.uuid4().hex[:10]}"
        started = time.time()
        
        # The prompt carries the verification command (run_executor encodes it).
        # Optional metadata for expected output: spec.metadata.get("expected_output")
        cmd = spec.prompt
        expected = ""
        if hasattr(spec, "metadata") and isinstance(getattr(spec, "metadata", None), dict):
            expected = spec.metadata.get("expected_output", "") or ""
        
        timeout = spec.timeout_seconds or self._default_timeout
        cwd = spec.cwd or os.getcwd()
        
        # Run synchronously. spawn() blocks; this is fine because the
        # orchestrator's per-task loop is also synchronous.
        try:
            proc = subprocess.run(
                cmd,
                shell=True,
                capture_output=True,
                text=True,
                timeout=timeout,
                cwd=cwd,
            )
            stdout, stderr, exit_code = proc.stdout, proc.stderr, proc.returncode
            timed_out = False
        except subprocess.TimeoutExpired as e:
            stdout = e.stdout.decode("utf-8", "replace") if isinstance(e.stdout, bytes) else (e.stdout or "")
            stderr = e.stderr.decode("utf-8", "replace") if isinstance(e.stderr, bytes) else (e.stderr or "")
            exit_code = -1
            timed_out = True
        except FileNotFoundError as e:
            # Shell itself missing — should never happen, but handle it
            stdout, stderr, exit_code = "", str(e), 127
            timed_out = False
        
        finished = time.time()
        
        # Determine status honestly
        if timed_out:
            status = AdapterStatus.TIMED_OUT
        elif exit_code != 0:
            status = AdapterStatus.FAILED
        elif expected and expected not in stdout:
            # Command "succeeded" but expected output not present → fail
            status = AdapterStatus.FAILED
        else:
            status = AdapterStatus.COMPLETE
        
        self._runs[handle_id] = _LocalRun(
            handle_id=handle_id,
            spec=spec,
            started_at=started,
            finished_at=finished,
            status=status,
            stdout=stdout,
            stderr=stderr,
            exit_code=exit_code,
            expected_substring=expected,
        )
        
        return AdapterRunHandle(
            handle_id=handle_id,
            backend_id=self._backend_id,
            spawned_at=started,
            spec_id=spec.spec_id,
        )
    
    def poll(self, handle: AdapterRunHandle) -> AdapterStatus:
        run = self._runs.get(handle.handle_id)
        if run is None:
            return AdapterStatus.FAILED
        return run.status
    
    def collect(self, handle: AdapterRunHandle) -> AdapterRunResult:
        run = self._runs.get(handle.handle_id)
        if run is None:
            return AdapterRunResult(
                handle_id=handle.handle_id,
                status=AdapterStatus.FAILED,
                error="unknown handle",
            )
        
        # Build a summary that surfaces the truth
        summary_lines = [
            f"command: {run.spec.prompt}",
            f"exit_code: {run.exit_code}",
            f"status: {run.status.value}",
        ]
        if run.expected_substring:
            present = run.expected_substring in run.stdout
            summary_lines.append(f"expected_substring_present: {present}")
        
        error_msg = ""
        if run.status == AdapterStatus.FAILED:
            if run.exit_code != 0:
                error_msg = f"command exited {run.exit_code}: {run.stderr.strip()[:200]}"
            elif run.expected_substring and run.expected_substring not in run.stdout:
                error_msg = (
                    f"expected substring {run.expected_substring!r} not found in stdout"
                )
        elif run.status == AdapterStatus.TIMED_OUT:
            error_msg = f"command timed out after {run.spec.timeout_seconds}s"
        
        return AdapterRunResult(
            handle_id=handle.handle_id,
            status=run.status,
            artifact_paths=[],  # local shell doesn't fabricate artifacts
            summary="\n".join(summary_lines),
            error=error_msg,
            started_at=run.started_at,
            finished_at=run.finished_at,
        )
    
    def kill(self, handle: AdapterRunHandle) -> None:
        # Synchronous adapter — by the time the caller has a handle, the
        # subprocess has already returned. Mark killed only if still running
        # (which it won't be in practice).
        run = self._runs.get(handle.handle_id)
        if run is None:
            return
        if run.status == AdapterStatus.RUNNING:
            run.status = AdapterStatus.KILLED

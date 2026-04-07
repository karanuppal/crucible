"""Phase 8 §28: OpenClaw sub-agent adapter (event-backed sync facade).

Wraps `sessions_spawn(runtime="subagent")` as a `BackendAdapter`. The
embedding host is responsible for actually invoking sessions_spawn and
delivering completion events to the adapter via `ingest_event()`.

Persisted adapter state under `runs/<run_id>/adapter-state/<handle_id>.json`
is the authoritative source for poll() and collect() after spawn — no
process-local listener state is required for correctness.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass
from typing import Any, Callable

from crucible.accelerators.adapters import (
    BackendAdapter, AdapterRunSpec, AdapterRunHandle, AdapterRunResult,
    AdapterStatus,
)
from crucible.accelerators.capabilities import (
    BackendCapabilities, Capability,
)
from crucible.runtime.run_store import RunStore


# The host provides a callable that actually spawns a sub-agent and
# returns a session id. This is intentionally injected so the adapter
# can be tested without OpenClaw being present.
SpawnCallable = Callable[[AdapterRunSpec], str]  # returns openclaw_session_id


def default_openclaw_capabilities(backend_id: str = "openclaw-subagent") -> BackendCapabilities:
    return BackendCapabilities(
        backend_id=backend_id,
        supports={
            Capability.SHELL_EXEC,
            Capability.FILE_WRITE,
            Capability.NETWORK,
            Capability.LONG_RUNNING,
            Capability.STREAMING_PROGRESS,
            Capability.INTERRUPTIBLE,
            Capability.ARTIFACT_PRODUCTION,
            Capability.SUB_AGENT_SPAWN,
        },
        max_concurrent_runs=4,
        declared_models=["claude", "codex", "gpt-5.4"],
    )


@dataclass
class _AdapterState:
    """In-memory mirror of persisted adapter state."""
    handle_id: str
    openclaw_session_id: str
    status: AdapterStatus
    started_at: float
    finished_at: float | None = None
    artifact_paths: list[str] | None = None
    summary: str = ""
    error: str = ""
    kill_requested: bool = False
    last_event_at: float = 0.0


class OpenClawSubagentAdapter(BackendAdapter):
    """Event-backed sync facade over OpenClaw sub-agents.
    
    Lifecycle:
    - spawn(): calls injected spawn_fn → returns session_id; persists initial state
    - external host calls ingest_event(handle_id, event) when push messages arrive
    - poll(handle): reads persisted state
    - collect(handle): returns terminal AdapterRunResult from persisted state
    - kill(handle): marks kill_requested
    """
    
    def __init__(
        self,
        run_store: RunStore,
        spawn_fn: SpawnCallable,
        *,
        backend_id: str = "openclaw-subagent",
        capabilities: BackendCapabilities | None = None,
    ) -> None:
        self._run_store = run_store
        self._spawn_fn = spawn_fn
        self._backend_id = backend_id
        self._caps = capabilities or default_openclaw_capabilities(backend_id)
    
    def backend_id(self) -> str:
        return self._backend_id
    
    def declared_capabilities(self) -> BackendCapabilities:
        return self._caps
    
    def spawn(self, spec: AdapterRunSpec) -> AdapterRunHandle:
        if not self._caps.supports_all(spec.required_capabilities):
            missing = spec.required_capabilities - self._caps.supports
            raise ValueError(
                f"OpenClawSubagentAdapter does not support required capabilities: {sorted(c.value for c in missing)}"
            )
        
        handle_id = f"{self._backend_id}-{uuid.uuid4().hex[:10]}"
        now = time.time()
        
        # Call host to actually spawn the sub-agent
        try:
            openclaw_session_id = self._spawn_fn(spec)
        except Exception as e:
            # Persist failed spawn state so collect() can read it
            self._run_store.write_adapter_state(handle_id, {
                "handle_id": handle_id,
                "openclaw_session_id": "",
                "status": AdapterStatus.FAILED.value,
                "started_at": now,
                "finished_at": now,
                "error": f"spawn failed: {e}",
            })
            self._run_store.append_adapter_log(f"{handle_id} spawn FAILED: {e}")
            return AdapterRunHandle(
                handle_id=handle_id,
                backend_id=self._backend_id,
                spawned_at=now,
                spec_id=spec.spec_id,
            )
        
        # Persist initial RUNNING state
        self._run_store.write_adapter_state(handle_id, {
            "handle_id": handle_id,
            "openclaw_session_id": openclaw_session_id,
            "status": AdapterStatus.RUNNING.value,
            "started_at": now,
            "finished_at": None,
            "artifact_paths": [],
            "summary": "",
            "error": "",
            "kill_requested": False,
            "last_event_at": now,
            "spec_id": spec.spec_id,
        })
        self._run_store.append_adapter_log(
            f"{handle_id} spawn -> session={openclaw_session_id} spec={spec.spec_id}"
        )
        
        return AdapterRunHandle(
            handle_id=handle_id,
            backend_id=self._backend_id,
            spawned_at=now,
            spec_id=spec.spec_id,
        )
    
    def poll(self, handle: AdapterRunHandle) -> AdapterStatus:
        state = self._run_store.read_adapter_state(handle.handle_id)
        if state is None:
            return AdapterStatus.FAILED
        try:
            return AdapterStatus(state.get("status", "failed"))
        except ValueError:
            return AdapterStatus.FAILED
    
    def collect(self, handle: AdapterRunHandle) -> AdapterRunResult:
        state = self._run_store.read_adapter_state(handle.handle_id)
        if state is None:
            return AdapterRunResult(
                handle_id=handle.handle_id,
                status=AdapterStatus.FAILED,
                error="no persisted adapter state",
            )
        try:
            status = AdapterStatus(state.get("status", "failed"))
        except ValueError:
            status = AdapterStatus.FAILED
        
        return AdapterRunResult(
            handle_id=handle.handle_id,
            status=status,
            artifact_paths=list(state.get("artifact_paths") or []),
            summary=state.get("summary", ""),
            error=state.get("error", ""),
            started_at=state.get("started_at", 0.0),
            finished_at=state.get("finished_at") or 0.0,
        )
    
    def kill(self, handle: AdapterRunHandle) -> None:
        state = self._run_store.read_adapter_state(handle.handle_id)
        if state is None:
            return
        state["kill_requested"] = True
        # Without a real cancel signal, mark as killed if still running
        try:
            current = AdapterStatus(state.get("status", "running"))
        except ValueError:
            current = AdapterStatus.RUNNING
        if current in {AdapterStatus.RUNNING, AdapterStatus.PENDING}:
            state["status"] = AdapterStatus.KILLED.value
            state["finished_at"] = time.time()
        self._run_store.write_adapter_state(handle.handle_id, state)
        self._run_store.append_adapter_log(f"{handle.handle_id} kill requested")
    
    # ─── External event ingestion ───
    
    def ingest_event(
        self,
        handle_id: str,
        *,
        status: AdapterStatus | None = None,
        artifact_paths: list[str] | None = None,
        summary: str | None = None,
        error: str | None = None,
        terminal: bool = False,
    ) -> None:
        """Update persisted adapter state from a push event.
        
        Called by the host when an OpenClaw sub-agent emits progress or completion.
        Idempotent: writing the same terminal state twice is safe.
        """
        state = self._run_store.read_adapter_state(handle_id)
        if state is None:
            self._run_store.append_adapter_log(f"ingest_event for unknown handle {handle_id}")
            return
        
        # Don't overwrite a terminal state with a non-terminal update
        try:
            existing = AdapterStatus(state.get("status", "running"))
        except ValueError:
            existing = AdapterStatus.RUNNING
        terminal_states = {
            AdapterStatus.COMPLETE,
            AdapterStatus.FAILED,
            AdapterStatus.KILLED,
            AdapterStatus.TIMED_OUT,
            AdapterStatus.PARTIAL,
        }
        if existing in terminal_states and status is None:
            return
        
        if status is not None:
            state["status"] = status.value
        if artifact_paths is not None:
            state["artifact_paths"] = list(artifact_paths)
        if summary is not None:
            state["summary"] = summary
        if error is not None:
            state["error"] = error
        if terminal or (status is not None and status in terminal_states):
            state["finished_at"] = time.time()
        
        state["last_event_at"] = time.time()
        self._run_store.write_adapter_state(handle_id, state)
        self._run_store.append_adapter_log(
            f"{handle_id} ingest status={state['status']}"
            + (f" terminal" if state.get("finished_at") else "")
        )

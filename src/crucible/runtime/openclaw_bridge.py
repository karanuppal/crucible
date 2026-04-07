"""Phase 8 §28.3: OpenClaw bridge — reference implementation.

This is the layer that turns OpenClaw's `sessions_spawn` + push event
delivery into something Crucible's `OpenClawSubagentAdapter` can drive
synchronously.

Two implementations live here:

1. `SimulatedOpenClawBridge` — used by tests and the Crucible CLI to
   simulate OpenClaw's behavior in-process. Drives the adapter through
   the full lifecycle without touching the network.

2. `SessionsSpawnBridge` — the production shim. Embedders construct it
   with two callables:
       spawn_callable(prompt, **kwargs) -> openclaw_session_id
       register_completion_callback(session_id, callback)
   The bridge wires these into the adapter's `ingest_event()` API and
   blocks the caller until the session reports terminal state (or until
   a timeout fires).

The contract is intentionally narrow: the embedder owns the OpenClaw
plumbing, but Crucible owns the bridge. There is no "the embedder will
handle this" — the bridge IS the integration point.
"""

from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable

from crucible.accelerators.adapters import (
    AdapterRunSpec, AdapterStatus,
)
from crucible.runtime.openclaw_adapter import OpenClawSubagentAdapter
from crucible.runtime.run_store import RunStore


# ─────────────────────────────────────────────────────────────────
# Bridge protocol
# ─────────────────────────────────────────────────────────────────

@dataclass
class BridgeOutcome:
    """The result of running one spec through a bridge."""
    handle_id: str
    openclaw_session_id: str
    status: AdapterStatus
    artifact_paths: list[str] = field(default_factory=list)
    summary: str = ""
    error: str = ""


# ─────────────────────────────────────────────────────────────────
# Simulated bridge (for tests + CLI default fallback)
# ─────────────────────────────────────────────────────────────────

class SimulatedOpenClawBridge:
    """Simulates an OpenClaw sub-agent without spawning anything.
    
    Useful for:
    - tests that exercise the bridge contract without needing a real OpenClaw
    - the standalone CLI when no OpenClaw daemon is available
    
    Behavior is controllable via the constructor:
      outcome: AdapterStatus to report (default COMPLETE)
      artifacts: artifact paths to "produce"
      delay_seconds: simulate work
    """
    
    def __init__(
        self,
        run_store: RunStore,
        *,
        outcome: AdapterStatus = AdapterStatus.COMPLETE,
        artifacts: list[str] | None = None,
        summary: str = "simulated run complete",
        error: str = "",
        delay_seconds: float = 0.0,
    ) -> None:
        self._store = run_store
        self._outcome = outcome
        self._artifacts = artifacts or []
        self._summary = summary
        self._error = error
        self._delay = delay_seconds
        self._adapter = OpenClawSubagentAdapter(
            run_store=run_store,
            spawn_fn=self._fake_spawn,
        )
    
    @property
    def adapter(self) -> OpenClawSubagentAdapter:
        return self._adapter
    
    def _fake_spawn(self, spec: AdapterRunSpec) -> str:
        return f"sim-session-{spec.spec_id}-{uuid.uuid4().hex[:6]}"
    
    def run_spec_to_completion(self, spec: AdapterRunSpec, *, timeout_seconds: float = 30.0) -> BridgeOutcome:
        """Spawn + drive the adapter to terminal state synchronously."""
        handle = self._adapter.spawn(spec)
        
        if self._delay > 0:
            time.sleep(min(self._delay, timeout_seconds))
        
        # Push the simulated terminal event
        self._adapter.ingest_event(
            handle.handle_id,
            status=self._outcome,
            artifact_paths=self._artifacts,
            summary=self._summary,
            error=self._error,
            terminal=True,
        )
        
        result = self._adapter.collect(handle)
        state = self._store.read_adapter_state(handle.handle_id) or {}
        return BridgeOutcome(
            handle_id=handle.handle_id,
            openclaw_session_id=state.get("openclaw_session_id", ""),
            status=result.status,
            artifact_paths=result.artifact_paths,
            summary=result.summary,
            error=result.error,
        )


# ─────────────────────────────────────────────────────────────────
# Production shim
# ─────────────────────────────────────────────────────────────────

# A SpawnCallable takes a prompt + kwargs and returns an OpenClaw session id.
# The embedder provides this and is responsible for actually invoking
# OpenClaw's sessions_spawn API.
SpawnCallable = Callable[..., str]

# A WaitCallable blocks until the given session reaches terminal state and
# returns a dict with at least: status (AdapterStatus value), artifact_paths,
# summary, error. The embedder provides this and is responsible for listening
# to OpenClaw's push completion events.
WaitCallable = Callable[[str, float], dict[str, Any]]


class SessionsSpawnBridge:
    """Production bridge over OpenClaw `sessions_spawn` + push completion.
    
    Embedders construct this with two callables (see typedefs above) and
    Crucible drives it synchronously per-spec. Internally:
      1. spawn() invokes spawn_callable, persists initial state via the adapter
      2. wait() invokes wait_callable, ingests the terminal event into the adapter
      3. collect() returns the persisted result
    
    Process restart safety: because every state transition is persisted by
    the adapter into the run store, a crashed bridge can be recreated and
    `collect()` will still return the right answer if the underlying
    `wait_callable` is idempotent.
    """
    
    def __init__(
        self,
        run_store: RunStore,
        *,
        spawn_callable: SpawnCallable,
        wait_callable: WaitCallable,
        backend_id: str = "openclaw-subagent",
    ) -> None:
        self._store = run_store
        self._wait = wait_callable
        self._adapter = OpenClawSubagentAdapter(
            run_store=run_store,
            spawn_fn=lambda spec: spawn_callable(
                prompt=spec.prompt,
                spec_id=spec.spec_id,
                cwd=spec.cwd,
                timeout_seconds=spec.timeout_seconds,
                metadata=getattr(spec, "metadata", {}) or {},
            ),
            backend_id=backend_id,
        )
    
    @property
    def adapter(self) -> OpenClawSubagentAdapter:
        return self._adapter
    
    def run_spec_to_completion(
        self,
        spec: AdapterRunSpec,
        *,
        timeout_seconds: float = 600.0,
    ) -> BridgeOutcome:
        """Spawn the OpenClaw sub-agent, wait for completion, return result."""
        handle = self._adapter.spawn(spec)
        state = self._store.read_adapter_state(handle.handle_id) or {}
        session_id = state.get("openclaw_session_id", "")
        
        if not session_id or state.get("status") == AdapterStatus.FAILED.value:
            # Spawn already failed
            return BridgeOutcome(
                handle_id=handle.handle_id,
                openclaw_session_id="",
                status=AdapterStatus.FAILED,
                error=state.get("error", "spawn failed"),
            )
        
        try:
            wait_result = self._wait(session_id, timeout_seconds)
        except Exception as e:
            self._adapter.ingest_event(
                handle.handle_id,
                status=AdapterStatus.FAILED,
                error=f"wait callable raised: {e}",
                terminal=True,
            )
            return BridgeOutcome(
                handle_id=handle.handle_id,
                openclaw_session_id=session_id,
                status=AdapterStatus.FAILED,
                error=f"wait callable raised: {e}",
            )
        
        # Map wait_result into ingest_event
        try:
            status = AdapterStatus(wait_result.get("status", "failed"))
        except ValueError:
            status = AdapterStatus.FAILED
        
        self._adapter.ingest_event(
            handle.handle_id,
            status=status,
            artifact_paths=wait_result.get("artifact_paths", []),
            summary=wait_result.get("summary", ""),
            error=wait_result.get("error", ""),
            terminal=True,
        )
        
        result = self._adapter.collect(handle)
        return BridgeOutcome(
            handle_id=handle.handle_id,
            openclaw_session_id=session_id,
            status=result.status,
            artifact_paths=result.artifact_paths,
            summary=result.summary,
            error=result.error,
        )

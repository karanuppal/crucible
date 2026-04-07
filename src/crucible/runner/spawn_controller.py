"""Phase 2: Role templates and spawn controller.

From spec (§9.3):
- Role-specific behavior, backend, model, timeout, retry budget
- SpawnController manages lifecycle
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Callable

from crucible.runner.run_graph import RunGraph, RunStatus, RunRole


# Role-specific configuration templates
ROLE_TEMPLATES: dict[RunRole, dict[str, Any]] = {
    RunRole.BUILDER: {
        "backend": "codex",
        "default_model": "gpt-5.4",
        "timeout_seconds": 600,  # 10 min
        "retry_budget": 2,
        "requires_evidence": True,
    },
    RunRole.REVIEWER: {
        "backend": "codex",
        "default_model": "gpt-5.4",
        "timeout_seconds": 300,  # 5 min
        "retry_budget": 1,
        "requires_evidence": True,
    },
    RunRole.DEBUGGER: {
        "backend": "codex",
        "default_model": "opus",
        "timeout_seconds": 300,
        "retry_budget": 3,
        "requires_evidence": True,
    },
    RunRole.RESEARCHER: {
        "backend": "codex",
        "default_model": "gpt-5.4",
        "timeout_seconds": 180,
        "retry_budget": 1,
        "requires_evidence": False,
    },
    RunRole.INTEGRATOR: {
        "backend": "codex",
        "default_model": "opus",
        "timeout_seconds": 600,
        "retry_budget": 2,
        "requires_evidence": True,
    },
    RunRole.SALVAGE: {
        "backend": "codex",
        "default_model": "opus",
        "timeout_seconds": 900,  # 15 min
        "retry_budget": 1,
        "requires_evidence": True,
    },
}


@dataclass
class SpawnConfig:
    """Configuration for spawning a sub-agent."""
    role: RunRole
    task_id: str
    parent_run_id: str = ""
    model: str | None = None
    timeout_seconds: int | None = None
    blocking: bool = True
    cwd: str | None = None
    payload: dict[str, Any] = field(default_factory=dict)


@dataclass
class SpawnResult:
    """Result of spawning a run."""
    run_id: str
    success: bool
    error: str | None = None


class SpawnController:
    """Manages sub-agent spawning and lifecycle.
    
    Responsibilities:
    - Create runs in graph
    - Apply role templates
    - Track active runs
    - Handle timeout/cancellation propagation
    """
    
    def __init__(
        self,
        run_graph: RunGraph,
        spawn_fn: Callable[[SpawnConfig], SpawnResult] | None = None,
    ) -> None:
        self._graph = run_graph
        self._spawn_fn = spawn_fn or self._default_spawn
        # run_id -> dict with start_time, timeout, backend_handle
        self._active_runs: dict[str, dict[str, Any]] = {}
    
    def spawn(self, config: SpawnConfig) -> SpawnResult:
        """Spawn a new sub-agent run.
        
        Returns SpawnResult with run_id set to the GRAPH run_id (not backend handle).
        Backend handle is tracked separately in active_runs metadata.
        """
        # Apply role template defaults
        template = ROLE_TEMPLATES.get(config.role, {})
        
        if config.model is None:
            config.model = template.get("default_model")
        if config.timeout_seconds is None:
            config.timeout_seconds = template.get("timeout_seconds", 300)
        
        # Create graph node
        run_id = self._graph.spawn(
            task_id=config.task_id,
            role=config.role,
            parent_run_id=config.parent_run_id,
            blocking=config.blocking,
        )
        
        # Mark as running
        self._graph.update_status(run_id, RunStatus.RUNNING)
        self._active_runs[run_id] = {
            "start_time": time.time(),
            "timeout_seconds": config.timeout_seconds,
            "backend_handle": None,
        }
        
        # Actually spawn the subprocess
        backend_result = self._spawn_fn(config)
        
        if not backend_result.success:
            self._graph.update_status(run_id, RunStatus.FAILED)
            self._active_runs.pop(run_id, None)
            return SpawnResult(run_id=run_id, success=False, error=backend_result.error)
        
        # Store backend handle for later reference
        self._active_runs[run_id]["backend_handle"] = backend_result.run_id
        
        # Return graph run_id as the canonical identifier
        return SpawnResult(run_id=run_id, success=True)
    
    def _default_spawn(self, config: SpawnConfig) -> SpawnResult:
        """Default spawn — override for actual subprocess spawning."""
        return SpawnResult(run_id="", success=False, error="No spawn function configured")
    
    def check_timeouts(self) -> list[str]:
        """Check for timed-out runs using per-run timeout (not just role default).
        
        Returns list of run_ids that timed out.
        Cascade-cancels their blocking children.
        """
        now = time.time()
        timed_out = []
        
        for run_id, meta in list(self._active_runs.items()):
            node = self._graph.get(run_id)
            if not node:
                self._active_runs.pop(run_id, None)
                continue
            
            # Use per-run timeout, not role template
            timeout = meta.get("timeout_seconds") or ROLE_TEMPLATES.get(node.role, {}).get("timeout_seconds", 300)
            
            if now - meta["start_time"] > timeout:
                cascaded = self._graph.update_status(run_id, RunStatus.TIMED_OUT)
                timed_out.append(run_id)
                self._active_runs.pop(run_id, None)
                # Clean up any cascaded child active entries
                for cid in cascaded:
                    self._active_runs.pop(cid, None)
        
        return timed_out
    
    def complete_run(self, run_id: str, status: RunStatus = RunStatus.COMPLETE) -> None:
        """Mark a run as complete."""
        self._graph.update_status(run_id, status)
        self._active_runs.pop(run_id, None)
    
    def cancel_blocking_children(self, parent_run_id: str) -> list[str]:
        """Cancel all blocking children of a run (both PENDING and RUNNING)."""
        cancelled = []
        children = self._graph.get_blocking_children(parent_run_id)
        
        for child_id in children:
            node = self._graph.get(child_id)
            if node and node.status in {RunStatus.PENDING, RunStatus.RUNNING}:
                self._graph.update_status(child_id, RunStatus.KILLED)
                cancelled.append(child_id)
                self._active_runs.pop(child_id, None)
        
        return cancelled
    
    def to_dict(self) -> dict[str, Any]:
        """Serialize active run state for persistence."""
        return {"active_runs": dict(self._active_runs)}
    
    def rehydrate(self, data: dict[str, Any]) -> None:
        """Restore active run tracking from persisted state."""
        self._active_runs = dict(data.get("active_runs", {}))
    
    def get_active_count(self) -> int:
        return len(self._active_runs)
    
    def get_config(self, role: RunRole) -> dict[str, Any]:
        return dict(ROLE_TEMPLATES.get(role, {}))
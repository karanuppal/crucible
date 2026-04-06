"""Phase 2: Sub-agent management cluster — Run graph model.

From spec (§9):
- Parent/child run relationships
- Blocking vs non-blocking children
- Detachment and reattachment semantics
- Cancellation propagation rules
- partial as first-class run outcome
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class RunStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETE = "complete"
    FAILED = "failed"
    PARTIAL = "partial"
    KILLED = "killed"
    TIMED_OUT = "timed_out"


class RunRole(str, Enum):
    BUILDER = "builder"
    REVIEWER = "reviewer"
    DEBUGGER = "debugger"
    RESEARCHER = "researcher"
    INTEGRATOR = "integrator"
    SALVAGE = "salvage"


@dataclass
class RunGraphNode:
    """A single run in the graph."""
    run_id: str
    task_id: str
    parent_run_id: str
    role: RunRole
    status: RunStatus
    blocking_children: list[str] = field(default_factory=list)
    detached_children: list[str] = field(default_factory=list)
    artifact_refs: list[str] = field(default_factory=list)
    summary: str = ""
    started_at: float = 0.0
    last_progress_at: float = 0.0


class RunGraph:
    """Manages the run graph with parent/child relationships.
    
    Key semantics from spec:
    - Every child has exactly one parent
    - Parent completion depends on all blocking children
    - Cancellation propagates to blocking children by default
    - Non-blocking children survive parent cancellation only if detached
    - partial is a valid terminal state
    """
    
    def __init__(self) -> None:
        self._nodes: dict[str, RunGraphNode] = {}
    
    def spawn(
        self,
        task_id: str,
        role: RunRole,
        parent_run_id: str = "",
        *,
        blocking: bool = True,
    ) -> str:
        """Create a new run node. Returns run_id."""
        run_id = f"run-{uuid.uuid4().hex[:8]}"
        node = RunGraphNode(
            run_id=run_id,
            task_id=task_id,
            parent_run_id=parent_run_id,
            role=role,
            status=RunStatus.PENDING,
        )
        
        # Register as child of parent
        if parent_run_id and parent_run_id in self._nodes:
            parent = self._nodes[parent_run_id]
            if blocking:
                parent.blocking_children.append(run_id)
            else:
                parent.detached_children.append(run_id)
        
        self._nodes[run_id] = node
        return run_id
    
    def get(self, run_id: str) -> RunGraphNode | None:
        return self._nodes.get(run_id)
    
    def update_status(self, run_id: str, status: RunStatus) -> None:
        if run_id in self._nodes:
            self._nodes[run_id].status = status
    
    def is_blocking_child_complete(self, run_id: str) -> bool:
        """Check if all blocking children of a run are in terminal state."""
        node = self._nodes.get(run_id)
        if not node:
            return True
        for child_id in node.blocking_children:
            child = self._nodes.get(child_id)
            if child and not self._is_terminal(child.status):
                return False
        return True
    
    def _is_terminal(self, status: RunStatus) -> bool:
        return status in {
            RunStatus.COMPLETE,
            RunStatus.FAILED,
            RunStatus.PARTIAL,
            RunStatus.KILLED,
            RunStatus.TIMED_OUT,
        }
    
    def get_blocking_children(self, run_id: str) -> list[str]:
        node = self._nodes.get(run_id)
        return list(node.blocking_children) if node else []
    
    def get_detached_children(self, run_id: str) -> list[str]:
        node = self._nodes.get(run_id)
        return list(node.detached_children) if node else []
    
    def detach_child(self, parent_run_id: str, child_run_id: str) -> None:
        """Detach a child from its parent (for non-blocking continuation)."""
        parent = self._nodes.get(parent_run_id)
        if parent and child_run_id in parent.blocking_children:
            parent.blocking_children.remove(child_run_id)
            parent.detached_children.append(child_run_id)
    
    def get_active_runs(self) -> list[RunGraphNode]:
        """Return all runs that are not in terminal state."""
        return [n for n in self._nodes.values() if not self._is_terminal(n.status)]
    
    def get_all_runs(self) -> list[RunGraphNode]:
        return list(self._nodes.values())
    
    def get_runs_for_task(self, task_id: str) -> list[RunGraphNode]:
        return [n for n in self._nodes.values() if n.task_id == task_id]
    
    def count(self) -> int:
        return len(self._nodes)
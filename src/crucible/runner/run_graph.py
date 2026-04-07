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
        self._task_owned_roots: set[str] = set()  # task_id-owned root runs
    
    def spawn(
        self,
        task_id: str,
        role: RunRole,
        parent_run_id: str = "",
        *,
        blocking: bool = True,
    ) -> str:
        """Create a new run node. Returns run_id.
        
        Ownership invariant: every child MUST have a real parent OR be a task-owned root.
        Spawning with an unknown parent_run_id raises ValueError (orphan prevention).
        """
        # Orphan prevention: parent must exist if specified
        if parent_run_id and parent_run_id not in self._nodes:
            raise ValueError(
                f"Cannot spawn child of unknown parent: {parent_run_id}. "
                "Either pass an existing parent_run_id or empty string for task-owned root."
            )
        
        run_id = f"run-{uuid.uuid4().hex[:8]}"
        node = RunGraphNode(
            run_id=run_id,
            task_id=task_id,
            parent_run_id=parent_run_id,
            role=role,
            status=RunStatus.PENDING,
        )
        
        # Register as child of parent, or as task-owned root
        if parent_run_id:
            parent = self._nodes[parent_run_id]
            if blocking:
                parent.blocking_children.append(run_id)
            else:
                parent.detached_children.append(run_id)
        else:
            # Task-owned root (no parent run, but owned by task)
            self._task_owned_roots.add(run_id)
        
        self._nodes[run_id] = node
        return run_id
    
    def reattach_child(self, child_run_id: str, new_owner_run_id: str | None, *, blocking: bool = True) -> None:
        """Reattach a child to a new owner run, or to its task as a root.
        
        Spec §9.2: detached children may continue only if explicitly reattached
        to another owning task or integration run.
        """
        child = self._nodes.get(child_run_id)
        if not child:
            raise ValueError(f"Unknown child: {child_run_id}")
        
        # Remove from old parent
        old_parent_id = child.parent_run_id
        if old_parent_id and old_parent_id in self._nodes:
            old_parent = self._nodes[old_parent_id]
            if child_run_id in old_parent.blocking_children:
                old_parent.blocking_children.remove(child_run_id)
            if child_run_id in old_parent.detached_children:
                old_parent.detached_children.remove(child_run_id)
        
        if new_owner_run_id is None:
            # Reattach to task as root
            child.parent_run_id = ""
            self._task_owned_roots.add(child_run_id)
        else:
            if new_owner_run_id not in self._nodes:
                raise ValueError(f"Unknown new owner: {new_owner_run_id}")
            new_owner = self._nodes[new_owner_run_id]
            child.parent_run_id = new_owner_run_id
            if blocking:
                new_owner.blocking_children.append(child_run_id)
            else:
                new_owner.detached_children.append(child_run_id)
            self._task_owned_roots.discard(child_run_id)
    
    def get(self, run_id: str) -> RunGraphNode | None:
        return self._nodes.get(run_id)
    
    def update_status(self, run_id: str, status: RunStatus) -> list[str]:
        """Update run status. If transitioning to a terminal cancellation state
        (KILLED, TIMED_OUT), automatically cancels all blocking children.
        
        Returns: list of child run_ids that were cascade-cancelled.
        """
        if run_id not in self._nodes:
            return []
        
        node = self._nodes[run_id]
        prev_status = node.status
        node.status = status
        
        cascaded: list[str] = []
        # Cancellation propagation: KILLED/TIMED_OUT/FAILED parents cancel blocking children
        if status in {RunStatus.KILLED, RunStatus.TIMED_OUT}:
            for child_id in list(node.blocking_children):
                child = self._nodes.get(child_id)
                if child and not self._is_terminal(child.status):
                    # Cascade cancel both PENDING and RUNNING children
                    cascaded.extend(self.update_status(child_id, RunStatus.KILLED))
                    cascaded.append(child_id)
        return cascaded
    
    def record_progress(self, run_id: str, timestamp: float | None = None) -> None:
        """Record liveness/progress heartbeat for a run."""
        import time as _time
        node = self._nodes.get(run_id)
        if node:
            node.last_progress_at = timestamp if timestamp is not None else _time.time()
    
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
    
    def to_dict(self) -> dict[str, Any]:
        """Serialize graph to dict for persistence."""
        return {
            "nodes": {
                rid: {
                    "run_id": n.run_id,
                    "task_id": n.task_id,
                    "parent_run_id": n.parent_run_id,
                    "role": n.role.value,
                    "status": n.status.value,
                    "blocking_children": list(n.blocking_children),
                    "detached_children": list(n.detached_children),
                    "artifact_refs": list(n.artifact_refs),
                    "summary": n.summary,
                    "started_at": n.started_at,
                    "last_progress_at": n.last_progress_at,
                }
                for rid, n in self._nodes.items()
            },
            "task_owned_roots": list(self._task_owned_roots),
        }
    
    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RunGraph:
        """Rehydrate graph from dict."""
        g = cls()
        for rid, n_data in data.get("nodes", {}).items():
            node = RunGraphNode(
                run_id=n_data["run_id"],
                task_id=n_data["task_id"],
                parent_run_id=n_data["parent_run_id"],
                role=RunRole(n_data["role"]),
                status=RunStatus(n_data["status"]),
                blocking_children=list(n_data.get("blocking_children", [])),
                detached_children=list(n_data.get("detached_children", [])),
                artifact_refs=list(n_data.get("artifact_refs", [])),
                summary=n_data.get("summary", ""),
                started_at=n_data.get("started_at", 0.0),
                last_progress_at=n_data.get("last_progress_at", 0.0),
            )
            g._nodes[rid] = node
        g._task_owned_roots = set(data.get("task_owned_roots", []))
        return g
    
    def save(self, path: str) -> None:
        """Persist graph to JSON file."""
        import json
        with open(path, "w") as f:
            json.dump(self.to_dict(), f, indent=2)
    
    @classmethod
    def load(cls, path: str) -> RunGraph:
        """Load graph from JSON file."""
        import json
        with open(path, "r") as f:
            return cls.from_dict(json.load(f))
    
    def attach_artifact(self, run_id: str, artifact_ref: str) -> None:
        """Attach an artifact to a run (used for PARTIAL salvage)."""
        node = self._nodes.get(run_id)
        if node:
            node.artifact_refs.append(artifact_ref)
    
    def mark_partial(self, run_id: str, summary: str, artifact_refs: list[str]) -> None:
        """Mark a run as PARTIAL with required salvageable artifacts.
        
        Spec §9.4: PARTIAL means usable artifacts were produced.
        At least one artifact ref is required.
        """
        if not artifact_refs:
            raise ValueError("PARTIAL state requires at least one artifact_ref (salvage requirement)")
        node = self._nodes.get(run_id)
        if not node:
            raise ValueError(f"Unknown run: {run_id}")
        node.artifact_refs.extend(artifact_refs)
        node.summary = summary
        self.update_status(run_id, RunStatus.PARTIAL)
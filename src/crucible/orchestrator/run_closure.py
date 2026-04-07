"""Run closure invariants for Crucible v5.4."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class RunClosureResult:
    terminal_status: str
    blockers: list[str] = field(default_factory=list)
    completed_tasks: list[str] = field(default_factory=list)
    failed_tasks: list[str] = field(default_factory=list)
    partial_tasks: list[str] = field(default_factory=list)


class RunClosure:
    def evaluate(
        self,
        task_states: list[dict[str, Any]],
        *,
        integration_required: bool = False,
        integration_complete: bool = True,
        post_validation_required: bool = False,
        post_validation_passed: bool = True,
    ) -> RunClosureResult:
        blockers: list[str] = []
        completed = [t["task_id"] for t in task_states if t.get("status") == "complete"]
        failed = [t["task_id"] for t in task_states if t.get("status") == "blocked"]
        active = [
            t["task_id"]
            for t in task_states
            if t.get("status") in {"building", "repairing", "debugging", "reviewing", "salvaging", "integrating", "validating"}
        ]
        awaiting = [t["task_id"] for t in task_states if t.get("status") == "awaiting_user"]

        if awaiting:
            blockers.append(f"awaiting_user:{','.join(awaiting)}")
            return RunClosureResult("blocked", blockers=blockers, completed_tasks=completed, failed_tasks=awaiting)
        if failed:
            blockers.append(f"blocked:{','.join(failed)}")
            terminal = "partial" if completed else "failed"
            return RunClosureResult(terminal, blockers=blockers, completed_tasks=completed, failed_tasks=failed)
        if active:
            return RunClosureResult("partial", completed_tasks=completed, partial_tasks=active)
        if integration_required and not integration_complete:
            blockers.append("integration_incomplete")
            return RunClosureResult("partial", blockers=blockers, completed_tasks=completed)
        if post_validation_required and not integration_required:
            blockers.append("post_validation_requires_integration")
            return RunClosureResult("failed", blockers=blockers, completed_tasks=completed)
        if post_validation_required and not integration_complete:
            blockers.append("post_validation_waiting_on_integration")
            return RunClosureResult("partial", blockers=blockers, completed_tasks=completed)
        if post_validation_required and not post_validation_passed:
            blockers.append("post_validation_failed")
            return RunClosureResult("failed", blockers=blockers, completed_tasks=completed)
        return RunClosureResult("complete", completed_tasks=completed)

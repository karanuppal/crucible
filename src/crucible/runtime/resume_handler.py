"""Resume handler for Crucible v5.4."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from crucible.runtime.run_store import RunStore


@dataclass
class ResumeSnapshot:
    run_id: str
    manifest_status: str
    semantic_state: str
    active_tasks: list[str]
    reconciled_attempts: list[str]


class ResumeHandler:
    def reconstruct(self, store: RunStore) -> ResumeSnapshot:
        manifest = store.read_manifest()
        if manifest is None:
            raise ValueError("manifest missing")
        reconciled = store.reconcile_in_flight_attempts()
        attempts = store.list_attempts()
        active_tasks = sorted({a.task_id for a in attempts if not a.finished_at or a.needs_reconciliation})
        semantic_state = self._semantic_state(manifest.current_status, attempts)
        return ResumeSnapshot(
            run_id=manifest.run_id,
            manifest_status=manifest.current_status,
            semantic_state=semantic_state,
            active_tasks=active_tasks,
            reconciled_attempts=[a.attempt_id for a in reconciled],
        )

    def _semantic_state(self, manifest_status: str, attempts: list[Any]) -> str:
        if manifest_status in {"complete", "failed", "blocked", "partial"}:
            return manifest_status
        if any(a.needs_reconciliation for a in attempts):
            return "repairing"
        if any(a.is_partial for a in attempts):
            return "salvaging"
        if any(a.status == "running" for a in attempts):
            return "building"
        return manifest_status or "queued"

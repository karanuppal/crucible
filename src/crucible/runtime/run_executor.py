"""Phase 8: Bridge between RunStore + Orchestrator.

Given a created RunStore + manifest + plan, this module:
  1. Builds a Router with backends (caller-supplied adapter factory)
  2. Materializes Phase 1 ledger / memory / registry alongside the run dir
  3. Constructs an Orchestrator
  4. Invokes run_build() and streams events into the run store
  5. Writes the final RunSummary

The CLI uses this for foreground execution. Embedders can also call it
directly with a custom adapter factory (e.g. an OpenClawSubagentAdapter
backed by real sessions_spawn).
"""

from __future__ import annotations

import os
import time
from typing import Any, Callable

from crucible.accelerators.adapters import BackendAdapter, AdapterStatus
from crucible.accelerators.capabilities import BackendCapabilityMatrix
from crucible.accelerators.router import Router
from crucible.orchestrator.orchestrator import (
    Orchestrator, OrchestratorPhase, TaskDefinition,
)
from crucible.runtime.plan_loader import plan_to_task_definitions
from crucible.runtime.run_store import (
    RunStore, RunManifest, RunSummary, CostSummary, TaskAttemptRecord,
)


AdapterFactory = Callable[[RunStore], list[BackendAdapter]]


def _terminal_status_from_orchestrator(state) -> str:
    if state.current_phase == OrchestratorPhase.DONE:
        if not state.failed_tasks:
            return "complete"
        if state.completed_tasks:
            return "partial"
        return "failed"
    if state.current_phase == OrchestratorPhase.BLOCKED:
        return "blocked"
    return "failed"


def execute_run(
    *,
    store: RunStore,
    manifest: RunManifest,
    plan: dict[str, Any],
    adapter_factory: AdapterFactory,
) -> RunSummary:
    """Execute a Crucible run end-to-end against the given run store.
    
    Returns the RunSummary that was written to result.json.
    """
    start = time.time()
    store.append_event("orchestrator_started", payload={})
    store.update_manifest_status("intake", "running")
    
    # Phase 1 substrate paths under the run dir
    ledger_path = os.path.join(store.run_root, "ledger.db")
    memory_path = os.path.join(store.run_root, "memory.db")
    registry_path = os.path.join(store.run_root, "registry.db")
    
    # Build adapters via factory
    try:
        adapters = adapter_factory(store)
    except Exception as e:
        store.append_event("adapter_factory_failed", payload={"error": str(e)})
        summary = RunSummary(
            run_id=manifest.run_id,
            terminal_status="failed",
            blocked_reason=f"adapter factory failed: {e}",
            total_runtime_seconds=time.time() - start,
        )
        store.write_result(summary)
        store.update_manifest_status("blocked", "failed")
        return summary
    
    if not adapters:
        store.append_event("no_backends", payload={})
        summary = RunSummary(
            run_id=manifest.run_id,
            terminal_status="blocked",
            blocked_reason="no backends configured",
            total_runtime_seconds=time.time() - start,
        )
        store.write_result(summary)
        store.update_manifest_status("blocked", "blocked")
        return summary
    
    # Build capability matrix + router
    matrix = BackendCapabilityMatrix()
    adapter_map: dict[str, BackendAdapter] = {}
    for adapter in adapters:
        matrix.register(adapter.declared_capabilities())
        adapter_map[adapter.backend_id()] = adapter
        store.append_adapter_log(f"registered backend {adapter.backend_id()}")
    
    router = Router(
        matrix=matrix,
        adapters=adapter_map,
        preferred_order=[a.backend_id() for a in adapters],
    )
    
    # Build orchestrator
    orchestrator = Orchestrator(
        project_id=manifest.project_id,
        build_id=manifest.build_id,
        ledger_path=ledger_path,
        memory_path=memory_path,
        registry_path=registry_path,
        router=router,
    )
    
    # Convert plan to TaskDefinitions
    tasks = plan_to_task_definitions(plan)
    store.append_event("tasks_loaded", payload={"task_count": len(tasks)})
    
    # Run!
    try:
        store.update_manifest_status("execute", "running")
        for task in tasks:
            store.append_event("task_dispatched", task_id=task.task_id, payload={
                "role": task.role.value if hasattr(task.role, 'value') else str(task.role),
                "intensity": task.intensity_hint,
            })
        
        final_state = orchestrator.run_build(
            spec_text=plan.get("spec", ""),
            tasks=tasks,
        )
        
        # Record per-task outcomes
        for tid in final_state.completed_tasks:
            store.append_event("task_completed", task_id=tid)
            attempt = TaskAttemptRecord(
                attempt_id=f"{tid}-attempt-0",
                task_id=tid,
                attempt_index=0,
                backend_id=adapters[0].backend_id(),
                status=AdapterStatus.COMPLETE.value,
                winning_attempt=True,
                started_at=start,
                finished_at=time.time(),
            )
            store.write_attempt(attempt)
        
        for tid in final_state.failed_tasks:
            store.append_event("task_failed", task_id=tid)
            attempt = TaskAttemptRecord(
                attempt_id=f"{tid}-attempt-0",
                task_id=tid,
                attempt_index=0,
                backend_id=adapters[0].backend_id(),
                status=AdapterStatus.FAILED.value,
                started_at=start,
                finished_at=time.time(),
            )
            store.write_attempt(attempt)
        
        terminal = _terminal_status_from_orchestrator(final_state)
        
        summary = RunSummary(
            run_id=manifest.run_id,
            terminal_status=terminal,
            completed_tasks=list(final_state.completed_tasks),
            failed_tasks=list(final_state.failed_tasks),
            blocked_reason=final_state.blocked_reason,
            total_runtime_seconds=time.time() - start,
            cost_summary=CostSummary(
                backends_used=[a.backend_id() for a in adapters],
                total_wall_clock_seconds=time.time() - start,
                subagents_spawned=len(tasks),
            ),
        )
        store.write_result(summary)
        store.update_manifest_status("done", terminal)
        store.append_event("run_terminal", payload={"terminal_status": terminal})
        return summary
    
    except Exception as e:
        store.append_event("orchestrator_crashed", payload={"error": str(e)})
        summary = RunSummary(
            run_id=manifest.run_id,
            terminal_status="failed",
            blocked_reason=f"orchestrator crash: {e}",
            total_runtime_seconds=time.time() - start,
        )
        store.write_result(summary)
        store.update_manifest_status("blocked", "failed")
        return summary

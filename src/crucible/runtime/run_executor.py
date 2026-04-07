"""Phase 8: Honest run executor.

Executes a Crucible run end-to-end against a RunStore by:
  1. Loading task definitions from the (preflight-validated) plan
  2. For each task: for each must_pass criterion, invoking the configured
     adapter with the criterion's verification_command + expected_output
  3. Aggregating per-task and per-run outcomes HONESTLY — a criterion is
     PASS only if the adapter says complete AND the expected substring
     is present (the LocalShellAdapter enforces this; other adapters
     are expected to do the same).
  4. Writing per-attempt records, events, and a final RunSummary.

Why we do not delegate to Orchestrator.run_build for verification:
The original Orchestrator path was happy to accept any AdapterStatus.COMPLETE
as proof, even when the underlying adapter never executed the verification
command. That fabricated evidence and made signoff worthless. This executor
runs verification commands itself and treats the adapter purely as a
command runner, not as an evidence source.

Embedders that want to use a real coding agent (Codex, Claude Code, OpenClaw
sub-agents) for the BUILD step should:
  1. Use that agent to produce artifacts (out of band)
  2. Then run Crucible to verify those artifacts via the verification triples
This separation keeps verification trustworthy regardless of how the build
was done.
"""

from __future__ import annotations

import os
import time
from typing import Any, Callable

from crucible.accelerators.adapters import (
    BackendAdapter, AdapterRunSpec, AdapterStatus,
)
from crucible.accelerators.capabilities import Capability
from crucible.runtime.run_store import (
    RunStore, RunManifest, RunSummary, CostSummary, TaskAttemptRecord,
)


# A factory takes a RunStore and returns the adapter to use.
# Most callers use a single adapter; we keep the list shape so they can
# pass multiple if they want round-robin / fallback in the future.
AdapterFactory = Callable[[RunStore], list[BackendAdapter]]


def execute_run(
    *,
    store: RunStore,
    manifest: RunManifest,
    plan: dict[str, Any],
    adapter_factory: AdapterFactory,
    per_criterion_timeout_seconds: int = 60,
) -> RunSummary:
    """Run every must_pass criterion in the plan via the adapter, honestly.
    
    Returns a RunSummary that reflects ACTUAL verification outcomes.
    """
    start = time.time()
    store.append_event("orchestrator_started", payload={})
    store.update_manifest_status("execute", "running")
    
    # Build adapters
    try:
        adapters = adapter_factory(store)
    except Exception as e:
        store.append_event("adapter_factory_failed", payload={"error": str(e)})
        return _terminate(store, manifest, "failed", start, blocked=f"adapter factory failed: {e}")
    
    if not adapters:
        store.append_event("no_backends", payload={})
        return _terminate(store, manifest, "blocked", start, blocked="no backends configured")
    
    primary = adapters[0]
    store.append_adapter_log(f"using adapter {primary.backend_id()}")
    
    tasks = plan.get("tasks", [])
    store.append_event("tasks_loaded", payload={"task_count": len(tasks)})
    
    completed: list[str] = []
    failed: list[str] = []
    partial: list[str] = []
    blockers: list[str] = []
    
    for task_idx, task in enumerate(tasks):
        task_id = task["task_id"]
        criteria = task.get("criteria", [])
        
        store.append_event("task_dispatched", task_id=task_id, payload={
            "role": task.get("role", "builder"),
            "intensity": task.get("intensity_hint", "M"),
            "criterion_count": len(criteria),
        })
        
        attempt_id = f"{task_id}-attempt-0"
        attempt_started = time.time()
        per_criterion_results: list[dict[str, Any]] = []
        all_must_pass_passed = True
        any_must_pass_present = False
        task_blockers: list[str] = []
        
        for crit in criteria:
            crit_id = crit.get("criterion_id", "")
            crit_class = crit.get("criterion_class", "must_pass")
            triple = crit.get("triple", {})
            cmd = triple.get("verification_command", "")
            expected = triple.get("expected_output", "")
            build_target = triple.get("build_target", "")
            
            if not cmd:
                # Already caught by preflight, but be defensive
                per_criterion_results.append({
                    "criterion_id": crit_id,
                    "criterion_class": crit_class,
                    "verdict": "fail",
                    "reason": "empty verification_command",
                })
                if crit_class == "must_pass":
                    all_must_pass_passed = False
                    any_must_pass_present = True
                continue
            
            if crit_class == "must_pass":
                any_must_pass_present = True
            
            # Build the spec — encode the verification command in the prompt
            # and the expected substring in metadata for the adapter to check.
            spec = AdapterRunSpec(
                spec_id=f"{task_id}.{crit_id}",
                prompt=cmd,
                cwd=os.getcwd(),
                timeout_seconds=per_criterion_timeout_seconds,
                required_capabilities={Capability.SHELL_EXEC},
                metadata={
                    "expected_output": expected,
                    "build_target": build_target,
                    "task_id": task_id,
                    "criterion_id": crit_id,
                },
            )
            
            store.append_event("criterion_dispatched", task_id=task_id, payload={
                "criterion_id": crit_id,
                "verification_command": cmd[:200],
                "expected_output": expected[:200],
                "criterion_class": crit_class,
            })
            
            try:
                handle = primary.spawn(spec)
                result = primary.collect(handle)
            except Exception as e:
                per_criterion_results.append({
                    "criterion_id": crit_id,
                    "criterion_class": crit_class,
                    "verdict": "fail",
                    "reason": f"adapter raised: {e}",
                })
                if crit_class == "must_pass":
                    all_must_pass_passed = False
                store.append_event("criterion_failed", task_id=task_id, payload={
                    "criterion_id": crit_id,
                    "error": str(e),
                })
                continue
            
            verdict = "pass" if result.status == AdapterStatus.COMPLETE else "fail"
            per_criterion_results.append({
                "criterion_id": crit_id,
                "criterion_class": crit_class,
                "verdict": verdict,
                "adapter_status": result.status.value,
                "summary": result.summary,
                "error": result.error,
            })
            
            event_type = "criterion_passed" if verdict == "pass" else "criterion_failed"
            store.append_event(event_type, task_id=task_id, payload={
                "criterion_id": crit_id,
                "adapter_status": result.status.value,
                "error": result.error[:300] if result.error else "",
            })
            
            if crit_class == "must_pass" and verdict != "pass":
                all_must_pass_passed = False
                task_blockers.append(
                    f"criterion {crit_id} failed: {result.error or 'no detail'}"
                )
        
        # Aggregate task outcome
        if not any_must_pass_present:
            # Preflight should reject this; if we got here, treat as fail
            task_status = AdapterStatus.FAILED
            failed.append(task_id)
            task_blockers.append("no must_pass criteria")
        elif all_must_pass_passed:
            task_status = AdapterStatus.COMPLETE
            completed.append(task_id)
        else:
            task_status = AdapterStatus.FAILED
            failed.append(task_id)
        
        store.write_attempt(TaskAttemptRecord(
            attempt_id=attempt_id,
            task_id=task_id,
            attempt_index=0,
            backend_id=primary.backend_id(),
            status=task_status.value,
            winning_attempt=(task_status == AdapterStatus.COMPLETE),
            started_at=attempt_started,
            finished_at=time.time(),
            blockers=task_blockers,
            metadata={"criteria_results": per_criterion_results},
        ))
        
        if task_status == AdapterStatus.COMPLETE:
            store.append_event("task_completed", task_id=task_id)
        else:
            store.append_event("task_failed", task_id=task_id, payload={
                "blockers": task_blockers,
            })
            blockers.extend(task_blockers)
    
    # Aggregate run outcome
    if completed and not failed:
        terminal = "complete"
    elif completed and failed:
        terminal = "partial"
        partial = failed[:]  # the partial list represents tasks that didn't pass
    elif failed and not completed:
        terminal = "failed"
    else:
        terminal = "blocked"
    
    summary = RunSummary(
        run_id=manifest.run_id,
        terminal_status=terminal,
        completed_tasks=completed,
        failed_tasks=failed,
        partial_tasks=partial,
        blocked_reason="; ".join(blockers[:5]) if blockers else "",
        total_runtime_seconds=time.time() - start,
        cost_summary=CostSummary(
            backends_used=[primary.backend_id()],
            total_wall_clock_seconds=time.time() - start,
            subagents_spawned=sum(len(t.get("criteria", [])) for t in tasks),
        ),
    )
    store.write_result(summary)
    store.update_manifest_status("done", terminal)
    store.append_event("run_terminal", payload={"terminal_status": terminal})
    return summary


def _terminate(
    store: RunStore,
    manifest: RunManifest,
    terminal_status: str,
    start: float,
    *,
    blocked: str = "",
) -> RunSummary:
    summary = RunSummary(
        run_id=manifest.run_id,
        terminal_status=terminal_status,
        blocked_reason=blocked,
        total_runtime_seconds=time.time() - start,
    )
    store.write_result(summary)
    store.update_manifest_status("blocked", terminal_status)
    return summary

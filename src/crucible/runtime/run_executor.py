"""Phase 8+: closed-loop runtime executor.

The v5.3 executor honestly ran verification commands, but it was still
single-pass and only emitted placeholder repair/review events. v5.4 keeps
that honesty while moving the deterministic task-closure loop into the real
runtime path.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import time
from pathlib import Path
from typing import Any, Callable

from crucible.accelerators.adapters import (
    BackendAdapter, AdapterRunSpec, AdapterStatus,
)
from crucible.accelerators.capabilities import Capability
from crucible.evidence.store import EvidenceManifest, EvidenceStore
from crucible.environment.existing_repo import ExistingRepoProvisionError, ensure_existing_repo_environment
from crucible.failures.evidence_packet import FailureClass, FailureEvidencePacket
from crucible.failures.next_action_selector import NextAction, NextActionSelector
from crucible.orchestrator.closed_loop_executor import ClosedLoopExecutor, TaskContext, TaskStatus
from crucible.orchestrator.run_closure import RunClosure
from crucible.policy.budget_tracker import BudgetTracker
from crucible.policy.circuit_breaker import CircuitBreaker
from crucible.runner.non_identical_rule import NonIdenticalRetryRule
from crucible.planning import PlanningError, ensure_validated_plan
from crucible.runtime.execution_models import (
    PromptAuditRecord,
    StructuredExecutionResult,
    ValidatorChainArtifact,
    build_execution_packet,
    evaluate_retry_admission,
    build_validation_policy,
    ensure_strategy_memory_artifact,
    is_bugfix_task,
    load_strategy_memory_artifact,
    normalize_review_policy,
    persist_prompt_audit_record,
    persist_repo_summary_artifact,
    persist_strategy_memory_artifact,
    persist_validator_chain_artifact,
    summarize_repo_context,
)
from crucible.runtime.run_store import (
    CostSummary,
    RunManifest,
    RunStore,
    RunSummary,
    TaskAttemptRecord,
)
from crucible.runtime.statuses import RunTerminalStatus, TaskTerminalStatus, legacy_run_status
from crucible.state.attempt_type import AttemptType
from crucible.state.workspace_record import WorkspaceLineageType, WorkspaceRecord
from crucible.workspace.manager import WorkspaceManager


AdapterFactory = Callable[[RunStore], list[BackendAdapter]]


TERMINAL_STATUSES = {
    TaskStatus.COMPLETE,
    TaskStatus.BLOCKED,
    TaskStatus.AWAITING_USER,
}


def _runtime_task_from_durable(task: dict[str, Any]) -> dict[str, Any]:
    review_policy = task.get("review_policy") if isinstance(task.get("review_policy"), dict) else {}
    criteria = task.get("criteria") if isinstance(task.get("criteria"), list) else []
    if not criteria:
        validation_policy = task.get("validation_policy") if isinstance(task.get("validation_policy"), dict) else {}
        must_pass = set(validation_policy.get("must_pass") or [])
        informational = set(validation_policy.get("informational") or [])
        criteria = []
        for index, command in enumerate(validation_policy.get("required_commands") or [], start=1):
            criterion_id = None
            if index <= len(validation_policy.get("must_pass") or []):
                criterion_id = (validation_policy.get("must_pass") or [])[index - 1]
            elif index - len(validation_policy.get("must_pass") or []) <= len(validation_policy.get("informational") or []):
                criterion_id = (validation_policy.get("informational") or [])[index - len(validation_policy.get("must_pass") or []) - 1]
            criterion_id = str(criterion_id or f"criterion-{index}")
            criterion_class = "informational" if criterion_id in informational and criterion_id not in must_pass else "must_pass"
            criteria.append({
                "criterion_id": criterion_id,
                "criterion_class": criterion_class,
                "triple": {
                    "verification_command": str(command or ""),
                    "expected_output": "",
                    "build_target": "",
                },
            })
    task_type = str(task.get("task_type") or "builder")
    return {
        "task_id": str(task["task_id"]),
        "description": str(task.get("description") or ""),
        "task_type": task_type,
        "role": task_type,
        "dependencies": [str(dep) for dep in task.get("dependencies", [])],
        "criteria": criteria,
        "review_policy": review_policy,
        "review_required": bool(review_policy.get("required", False)),
        "acceptance_criteria": list(task.get("acceptance_criteria") or []),
    }


def execute_run(
    *,
    store: RunStore,
    manifest: RunManifest,
    plan: dict[str, Any],
    adapter_factory: AdapterFactory,
    per_criterion_timeout_seconds: int = 60,
    workspace_root: str | None = None,
) -> RunSummary:
    start = time.time()
    workspace_root = os.path.abspath(workspace_root or manifest.workspace_root or os.getcwd())
    evidence_store = EvidenceStore(Path(store.run_root) / "evidence")
    workspace_manager = WorkspaceManager(Path(store.run_root) / "workspaces")

    try:
        durable_plan = ensure_validated_plan(store.read_plan())
    except PlanningError as e:
        store.append_event("plan_gate_failed", payload={"error": str(e), "plan_path": store.plan_path})
        return _terminate(store, manifest, "failed", start, blocked=f"validated plan required before execution: {e}")

    store.append_event(
        "orchestrator_started",
        payload={
            "workspace_root": workspace_root,
            "run_mode": "closed_loop",
            "plan_path": store.plan_path,
            "plan_status": durable_plan.get("status", "missing"),
        },
    )
    store.update_manifest_status("execute", "running")

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

    tasks = [_runtime_task_from_durable(task) for task in durable_plan.get("tasks", [])]
    store.append_event("tasks_loaded", payload={"task_count": len(tasks), "plan_source": store.plan_path})

    completed: list[str] = []
    failed: list[str] = []
    partial: list[str] = []
    blocked: list[str] = []
    escalated: list[str] = []
    cancelled: list[str] = []
    blockers: list[str] = []

    existing_winners = {
        a.task_id for a in store.list_attempts()
        if a.winning_attempt and a.status == AdapterStatus.COMPLETE.value
    }
    task_outcomes: dict[str, str] = {task_id: TaskTerminalStatus.SUCCEEDED.value for task_id in existing_winners}

    executor = ClosedLoopExecutor()
    pending_tasks = {task["task_id"]: task for task in tasks}

    while pending_tasks:
        progress_made = False
        for task_id, task in list(pending_tasks.items()):
            dependencies = [str(dep) for dep in task.get("dependencies", [])]
            unsatisfied = [dep for dep in dependencies if task_outcomes.get(dep) != TaskTerminalStatus.SUCCEEDED.value]
            terminal_predecessors = [dep for dep in unsatisfied if dep in task_outcomes]
            if terminal_predecessors:
                predecessor_states = {dep: task_outcomes[dep] for dep in terminal_predecessors}
                reason = "unmet task dependencies: " + ", ".join(
                    f"{dep}={predecessor_states[dep]}" for dep in terminal_predecessors
                )
                store.append_event("task_blocked", task_id=task_id, payload={
                    "reason": reason,
                    "semantic_state": TaskTerminalStatus.BLOCKED.value,
                    "dependencies": predecessor_states,
                })
                task_outcomes[task_id] = TaskTerminalStatus.BLOCKED.value
                blocked.append(task_id)
                blockers.append(reason)
                pending_tasks.pop(task_id)
                progress_made = True
                continue
            if unsatisfied:
                continue
            if task_id in existing_winners:
                store.append_event("task_skipped_already_complete", task_id=task_id, payload={})
                completed.append(task_id)
                task_outcomes[task_id] = TaskTerminalStatus.SUCCEEDED.value
                pending_tasks.pop(task_id)
                progress_made = True
                continue

            ctx = TaskContext(
                task_id=task_id,
                spec=task.get("description", ""),
                criteria=[c.get("criterion_id", "") for c in task.get("criteria", [])],
                review_required=task.get("review_required", False),
            )
            task_terminal, task_blockers = _execute_task_closed_loop(
                executor=executor,
                store=store,
                manifest=manifest,
                task=task,
                ctx=ctx,
                adapter=primary,
                workspace_root=workspace_root,
                workspace_manager=workspace_manager,
                evidence_store=evidence_store,
                per_criterion_timeout_seconds=per_criterion_timeout_seconds,
                max_attempts_per_task=durable_plan.get("global_policy", {}).get("max_attempts_per_task"),
            )

            if task_terminal == TaskTerminalStatus.SUCCEEDED.value:
                completed.append(task_id)
            elif task_terminal == "partial":
                partial.append(task_id)
            elif task_terminal == TaskTerminalStatus.BLOCKED.value:
                blocked.append(task_id)
            elif task_terminal == TaskTerminalStatus.ESCALATED.value:
                escalated.append(task_id)
            elif task_terminal == TaskTerminalStatus.CANCELLED.value:
                cancelled.append(task_id)
            else:
                failed.append(task_id)
            task_outcomes[task_id] = task_terminal
            blockers.extend(task_blockers)
            pending_tasks.pop(task_id)
            progress_made = True
        if progress_made:
            continue
        for task_id, task in list(pending_tasks.items()):
            unresolved = [dep for dep in task.get("dependencies", []) if dep not in task_outcomes]
            reason = "dependency resolution deadlock: " + ", ".join(str(dep) for dep in unresolved)
            store.append_event("task_blocked", task_id=task_id, payload={
                "reason": reason,
                "semantic_state": TaskTerminalStatus.BLOCKED.value,
                "dependencies": {str(dep): "unresolved" for dep in unresolved},
            })
            task_outcomes[task_id] = TaskTerminalStatus.BLOCKED.value
            blocked.append(task_id)
            blockers.append(reason)
            pending_tasks.pop(task_id)
        break

    task_states = ([{"task_id": task_id, "status": TaskTerminalStatus.SUCCEEDED.value} for task_id in completed]
        + [{"task_id": task_id, "status": TaskTerminalStatus.FAILED.value} for task_id in failed]
        + [{"task_id": task_id, "status": TaskTerminalStatus.BLOCKED.value} for task_id in blocked]
        + [{"task_id": task_id, "status": TaskTerminalStatus.ESCALATED.value} for task_id in escalated]
        + [{"task_id": task_id, "status": TaskTerminalStatus.CANCELLED.value} for task_id in cancelled]
        + [{"task_id": task_id, "status": "integrating"} for task_id in partial])
    closure = RunClosure().evaluate(
        task_states,
        integration_required=plan.get("integration_required", False),
        integration_complete=not plan.get("integration_required", False),
        post_validation_required=plan.get("post_integration_validation_required", False),
        post_validation_passed=not plan.get("post_integration_validation_required", False),
    )
    terminal = closure.terminal_status
    blockers = blockers + [b for b in closure.blockers if b not in blockers]

    if terminal == "complete":
        terminal = RunTerminalStatus.SUCCEEDED.value
    summary = RunSummary(
        run_id=manifest.run_id,
        terminal_status=terminal,
        completed_tasks=closure.completed_tasks,
        failed_tasks=sorted(set(failed + closure.failed_tasks)),
        partial_tasks=sorted(set(partial + closure.partial_tasks)),
        blocked_reason="; ".join(blockers[:5]) if blockers else "",
        integration_status="complete" if plan.get("integration_required", False) and not closure.blockers else ("pending" if plan.get("integration_required", False) else None),
        total_runtime_seconds=time.time() - start,
        cost_summary=CostSummary(
            backends_used=[primary.backend_id()],
            total_wall_clock_seconds=time.time() - start,
            retries_total=max(0, len(store.list_attempts()) - len(tasks)),
            subagents_spawned=len(store.list_attempts()),
        ),
    )
    store.write_result(summary)
    store.update_manifest_status("done", terminal)
    store.append_event("run_terminal", payload={"terminal_status": terminal, "legacy_terminal_status": legacy_run_status(terminal)})
    return summary


def _execute_task_closed_loop(
    *,
    executor: ClosedLoopExecutor,
    store: RunStore,
    manifest: RunManifest,
    task: dict[str, Any],
    ctx: TaskContext,
    adapter: BackendAdapter,
    workspace_root: str,
    workspace_manager: WorkspaceManager,
    evidence_store: EvidenceStore,
    per_criterion_timeout_seconds: int,
    max_attempts_per_task: int | None = None,
) -> tuple[str, list[str]]:
    task_id = task["task_id"]
    criteria = task.get("criteria", [])
    store.append_event("task_dispatched", task_id=task_id, payload={
        "role": task.get("role", "builder"),
        "intensity": task.get("intensity_hint", "M"),
        "criterion_count": len(criteria),
        "semantic_state": "building",
    })

    if not criteria:
        store.append_event("task_blocked", task_id=task_id, payload={"reason": "no criteria", "semantic_state": TaskTerminalStatus.BLOCKED.value})
        return "failed", ["no criteria"]

    task_blockers: list[str] = []
    ctx = executor.initialize_task(ctx)

    def _fail_task_for_stop(reason: str) -> TaskContext:
        nonlocal task_blockers
        task_blockers = [reason]
        ctx.status = TaskStatus.BLOCKED
        store.append_event("task_failed", task_id=task_id, attempt_id=(ctx.current_attempt.attempt_id if ctx.current_attempt else ""), payload={
            "reason": reason,
            "semantic_state": TaskTerminalStatus.FAILED.value,
        })
        return ctx

    def _attempt_runner(ctx: TaskContext, attempt: Any) -> TaskContext:
        nonlocal task_blockers
        workspace_record = _materialize_workspace(
            task_id=task_id,
            attempt_id=attempt.attempt_id,
            attempt_type=attempt.attempt_type,
            ctx=ctx,
            workspace_root=workspace_root,
            workspace_manager=workspace_manager,
            run_root=store.run_root,
        )
        attempt.workspace_record = workspace_record
        store.append_event(
            "workspace_created" if workspace_record.lineage_type == WorkspaceLineageType.FRESH else "workspace_inherited",
            task_id=task_id,
            attempt_id=attempt.attempt_id,
            payload={"workspace_id": workspace_record.workspace_id, "path": workspace_record.path, "workspace_mode": workspace_record.lineage_type.value},
        )
        store.append_event("attempt_started", task_id=task_id, attempt_id=attempt.attempt_id, payload={
            "attempt_type": attempt.attempt_type.value,
            "workspace_id": workspace_record.workspace_id,
            "workspace_mode": workspace_record.lineage_type.value,
        })

        result = _run_attempt(
            store=store,
            task=task,
            attempt_id=attempt.attempt_id,
            attempt_index=len(ctx.attempts) - 1,
            attempt_type=attempt.attempt_type,
            adapter=adapter,
            criteria=criteria,
            workspace_record=workspace_record,
            per_criterion_timeout_seconds=per_criterion_timeout_seconds,
            evidence_store=evidence_store,
            prior_attempts=ctx.attempts[:-1],
        )

        review_direct_action: str | None = None
        if result["attempt_record"].status == AdapterStatus.COMPLETE.value:
            attempt.output = {"criteria_results": result["criteria_results"]}
            if attempt.attempt_type == AttemptType.REVIEW:
                review_decision = _resolve_review_decision(
                    task=task,
                    review_attempt=attempt,
                    review_attempt_record=result["attempt_record"],
                    criteria_results=result["criteria_results"],
                    evidence_store=evidence_store,
                    prior_attempts=ctx.attempts[:-1],
                )
                result["attempt_record"].review_verdict = review_decision["verdict"]
                result["attempt_record"].next_action_chosen = review_decision["next_action"]
                result["attempt_record"].metadata["review_decision"] = {
                    **review_decision,
                    "failure_packet": review_decision["failure_packet"].to_dict() if review_decision["failure_packet"] is not None else None,
                }
                store.write_attempt(result["attempt_record"])
                if review_decision["verdict"] == "accept":
                    ctx.status = TaskStatus.COMPLETE
                    store.append_event("review_accepted", task_id=task_id, attempt_id=attempt.attempt_id, payload={"verdict": "accept", "accepted_attempt_id": review_decision["accepted_attempt_id"]})
                    store.append_event("task_completed", task_id=task_id, payload={"semantic_state": TaskTerminalStatus.SUCCEEDED.value, "winning_attempt_id": review_decision["accepted_attempt_id"]})
                    return ctx
                attempt.state = attempt.state.VALIDATED_FAIL
                attempt.failure_evidence = review_decision["failure_packet"]
                result["failure_packet"] = review_decision["failure_packet"]
                failure_packet = review_decision["failure_packet"]
                review_direct_action = review_decision["next_action"]
                store.append_event("review_rejected", task_id=task_id, attempt_id=attempt.attempt_id, payload={"verdict": "reject", "rejection_type": review_decision["rejection_type"], "rejected_attempt_id": review_decision["accepted_attempt_id"]})
            else:
                attempt.state = attempt.state.VALIDATED_PASS
                store.append_event("next_action_selected", task_id=task_id, attempt_id=attempt.attempt_id, payload={"action": NextAction.REVIEW.value if ctx.review_required else NextAction.COMPLETE.value})
                if ctx.review_required:
                    store.append_event("review_requested", task_id=task_id, attempt_id=attempt.attempt_id, payload={"attempt_type": "review"})
                    return executor._handle_validation_pass(ctx, attempt)
                ctx.status = TaskStatus.COMPLETE
                store.append_event("task_completed", task_id=task_id, payload={"semantic_state": TaskTerminalStatus.SUCCEEDED.value, "winning_attempt_id": attempt.attempt_id})
                return ctx

        if result["attempt_record"].status == AdapterStatus.PARTIAL.value:
            attempt.state = attempt.state.PARTIAL
        else:
            attempt.state = attempt.state.VALIDATED_FAIL
        attempt.failure_evidence = result.get("failure_packet")

        failure_packet = result.get("failure_packet")
        if failure_packet is None:
            task_blockers.append("attempt failed without failure packet")
            ctx.status = TaskStatus.BLOCKED
            return ctx

        if review_direct_action is not None:
            result["attempt_record"].next_action_chosen = review_direct_action
            result["attempt_record"].metadata["selector_reasoning"] = "reviewer-directed handoff"
            store.write_attempt(result["attempt_record"])
            attempt.output = {"criteria_results": result["criteria_results"]}
            task_blockers = list(result["attempt_record"].blockers)
            store.append_event("next_action_selected", task_id=task_id, attempt_id=attempt.attempt_id, payload={
                "action": review_direct_action,
                "rule_fired": "reviewer_directive",
                "attempt_type": "debug" if review_direct_action == NextAction.DEBUG.value else "repair",
            })
            if review_direct_action == NextAction.DEBUG.value:
                store.append_event("debug_scheduled", task_id=task_id, attempt_id=attempt.attempt_id, payload={"attempt_type": "debug"})
                return executor._start_debug(ctx)
            if review_direct_action == NextAction.REPAIR.value:
                store.append_event("repair_scheduled", task_id=task_id, attempt_id=attempt.attempt_id, payload={"attempt_type": "repair"})
                return executor._start_repair(ctx)

        budgets_remaining = ctx.budget_tracker.get_all_remaining() if ctx.budget_tracker is not None else {}
        attempt_history = [
            {"attempt_id": a.attempt_id, "signature": getattr(a.failure_evidence, "signature", None)}
            for a in ctx.attempts[:-1]
            if getattr(a, "failure_evidence", None) is not None
        ]
        decision = NextActionSelector.select(
            failure_packet,
            budgets_remaining,
            rejection_ledger=[{"attempt_id": a.attempt_id, "action": getattr(a, "next_action_chosen", "")} for a in ctx.attempts[:-1]],
            attempt_history=attempt_history,
            workspace_policy=task.get("workspace_policy", "fresh_per_attempt"),
        )
        result["attempt_record"].next_action_chosen = decision.action.value
        result["attempt_record"].metadata["selector_reasoning"] = decision.reasoning
        store.write_attempt(result["attempt_record"])
        attempt.output = {"criteria_results": result["criteria_results"]}
        task_blockers = list(result["attempt_record"].blockers)
        store.append_event("next_action_selected", task_id=task_id, attempt_id=attempt.attempt_id, payload={
            "action": decision.action.value,
            "rule_fired": decision.rule_fired,
            "attempt_type": decision.attempt_type.value if decision.attempt_type else "",
        })

        if decision.action == NextAction.AWAITING_USER:
            ctx.status = TaskStatus.AWAITING_USER
            store.append_event("task_failed", task_id=task_id, attempt_id=attempt.attempt_id, payload={
                "reason": failure_packet.human_summary,
                "semantic_state": TaskTerminalStatus.ESCALATED.value,
                "question_packet": decision.question_packet,
            })
            store.append_event("task_blocked", task_id=task_id, attempt_id=attempt.attempt_id, payload={
                "reason": failure_packet.human_summary,
                "semantic_state": TaskTerminalStatus.ESCALATED.value,
                "question_packet": decision.question_packet,
            })
            return ctx

        if decision.action == NextAction.BLOCKED:
            ctx.status = TaskStatus.BLOCKED
            if decision.rule_fired.startswith("budget_exhausted:"):
                store.append_event("task_failed", task_id=task_id, attempt_id=attempt.attempt_id, payload={
                    "reason": failure_packet.human_summary,
                    "semantic_state": TaskTerminalStatus.FAILED.value,
                })
            else:
                store.append_event("task_failed", task_id=task_id, attempt_id=attempt.attempt_id, payload={
                    "reason": failure_packet.human_summary,
                    "semantic_state": TaskTerminalStatus.BLOCKED.value,
                })
                store.append_event("task_blocked", task_id=task_id, attempt_id=attempt.attempt_id, payload={
                    "reason": failure_packet.human_summary,
                    "semantic_state": TaskTerminalStatus.BLOCKED.value,
                })
            return ctx

        if decision.action == NextAction.REPAIR:
            if max_attempts_per_task is not None and len(ctx.attempts) >= max_attempts_per_task:
                return _fail_task_for_stop(f"attempt budget exhausted at {max_attempts_per_task} total attempts")
            store.append_event("repair_scheduled", task_id=task_id, attempt_id=attempt.attempt_id, payload={"attempt_type": "repair"})
            ctx = executor._start_repair(ctx)
            if ctx.status == TaskStatus.BLOCKED:
                store.append_event("task_failed", task_id=task_id, attempt_id=attempt.attempt_id, payload={"reason": failure_packet.human_summary, "semantic_state": TaskTerminalStatus.FAILED.value})
            return ctx
        if decision.action == NextAction.DEBUG:
            if max_attempts_per_task is not None and len(ctx.attempts) >= max_attempts_per_task:
                return _fail_task_for_stop(f"attempt budget exhausted at {max_attempts_per_task} total attempts")
            store.append_event("debug_scheduled", task_id=task_id, attempt_id=attempt.attempt_id, payload={"attempt_type": "debug"})
            ctx = executor._start_debug(ctx)
            if ctx.status == TaskStatus.BLOCKED:
                store.append_event("task_failed", task_id=task_id, attempt_id=attempt.attempt_id, payload={"reason": failure_packet.human_summary, "semantic_state": TaskTerminalStatus.FAILED.value})
            return ctx
        if decision.action == NextAction.SALVAGE:
            if max_attempts_per_task is not None and len(ctx.attempts) >= max_attempts_per_task:
                return _fail_task_for_stop(f"attempt budget exhausted at {max_attempts_per_task} total attempts")
            store.append_event("salvage_scheduled", task_id=task_id, attempt_id=attempt.attempt_id, payload={"attempt_type": "salvage"})
            ctx = executor._start_salvage(ctx)
            if ctx.status == TaskStatus.BLOCKED:
                store.append_event("task_failed", task_id=task_id, attempt_id=attempt.attempt_id, payload={"reason": failure_packet.human_summary, "semantic_state": TaskTerminalStatus.FAILED.value})
            return ctx
        ctx.status = TaskStatus.BLOCKED
        store.append_event("task_failed", task_id=task_id, attempt_id=attempt.attempt_id, payload={"reason": f"unsupported next action {decision.action.value}", "semantic_state": TaskTerminalStatus.BLOCKED.value})
        store.append_event("task_blocked", task_id=task_id, attempt_id=attempt.attempt_id, payload={"reason": f"unsupported next action {decision.action.value}", "semantic_state": TaskTerminalStatus.BLOCKED.value})
        task_blockers = [f"unsupported next action {decision.action.value}"]
        return ctx

    ctx = executor.execute_task(ctx, attempt_runner=_attempt_runner)
    if ctx.status == TaskStatus.COMPLETE:
        return TaskTerminalStatus.SUCCEEDED.value, []
    if ctx.status in {TaskStatus.BUILDING, TaskStatus.REPAIRING, TaskStatus.DEBUGGING, TaskStatus.SALVAGING, TaskStatus.INTEGRATING}:
        return "partial", task_blockers or [ctx.status.value]
    if ctx.status == TaskStatus.AWAITING_USER:
        return TaskTerminalStatus.ESCALATED.value, task_blockers or [ctx.status.value]
    if ctx.status == TaskStatus.BLOCKED:
        semantic_states = {
            event.payload.get("semantic_state")
            for event in reversed(store.read_events())
            if event.task_id == task_id and event.type in {"task_failed", "task_blocked"}
        }
        if TaskTerminalStatus.CANCELLED.value in semantic_states:
            return TaskTerminalStatus.CANCELLED.value, task_blockers or [ctx.status.value]
        if TaskTerminalStatus.ESCALATED.value in semantic_states:
            return TaskTerminalStatus.ESCALATED.value, task_blockers or [ctx.status.value]
        if TaskTerminalStatus.FAILED.value in semantic_states:
            return TaskTerminalStatus.FAILED.value, task_blockers or [ctx.status.value]
        if TaskTerminalStatus.BLOCKED.value in semantic_states:
            return TaskTerminalStatus.BLOCKED.value, task_blockers or [ctx.status.value]
    return TaskTerminalStatus.FAILED.value, task_blockers or [ctx.status.value]


def _materialize_workspace(
    *,
    task_id: str,
    attempt_id: str,
    attempt_type: AttemptType,
    ctx: TaskContext,
    workspace_root: str,
    workspace_manager: WorkspaceManager,
    run_root: str,
) -> WorkspaceRecord:
    previous = ctx.attempts[-2] if len(ctx.attempts) >= 2 else None
    if previous is None:
        record = WorkspaceRecord(lineage_type=WorkspaceLineageType.FRESH, task_id=task_id)
    elif attempt_type == AttemptType.SALVAGE:
        record = WorkspaceRecord(lineage_type=WorkspaceLineageType.SALVAGE_INHERIT, task_id=task_id, basis_attempt_id=previous.attempt_id)
    elif attempt_type in {AttemptType.REPAIR, AttemptType.DEBUG, AttemptType.REVALIDATE, AttemptType.REVIEW}:
        record = WorkspaceRecord(lineage_type=WorkspaceLineageType.REPAIR_BASIS, task_id=task_id, basis_attempt_id=previous.attempt_id)
    else:
        record = WorkspaceRecord(lineage_type=WorkspaceLineageType.FRESH, task_id=task_id)
    record.workspace_id = attempt_id
    record = workspace_manager.create(record)
    if record.path is None:
        raise RuntimeError("workspace path missing")
    target_path = Path(record.path)
    exclude_roots = [Path(run_root).resolve()]
    if record.lineage_type == WorkspaceLineageType.FRESH:
        _copy_workspace(Path(workspace_root), target_path, exclude_roots=exclude_roots)
        try:
            provision_result = ensure_existing_repo_environment(str(target_path))
        except ExistingRepoProvisionError as exc:
            record.metadata["environment"] = exc.result.to_dict()
        else:
            record.metadata["environment"] = provision_result.to_dict()
    elif previous is not None and previous.workspace_record.path:
        _copy_workspace(Path(previous.workspace_record.path), target_path, exclude_roots=exclude_roots)
        if previous.workspace_record.metadata.get("environment"):
            record.metadata["environment"] = previous.workspace_record.metadata["environment"]
    return record


def _copy_workspace(src: Path, dest: Path, *, exclude_roots: list[Path] | None = None) -> None:
    if not src.exists():
        return
    exclude_roots = [p.resolve() for p in (exclude_roots or [])]
    for child in src.iterdir():
        resolved = child.resolve()
        if child.name in {"runs", ".git", "__pycache__", ".venv", "node_modules"}:
            continue
        if any(
            resolved == root or root in resolved.parents or resolved in root.parents
            for root in exclude_roots
        ):
            continue
        target = dest / child.name
        if child.is_dir():
            shutil.copytree(child, target, dirs_exist_ok=True)
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(child, target)


def _run_attempt(
    *,
    store: RunStore,
    task: dict[str, Any],
    attempt_id: str,
    attempt_index: int,
    attempt_type: AttemptType,
    adapter: BackendAdapter,
    criteria: list[dict[str, Any]],
    workspace_record: WorkspaceRecord,
    per_criterion_timeout_seconds: int,
    evidence_store: EvidenceStore,
    prior_attempts: list[Any],
) -> dict[str, Any]:
    if attempt_type == AttemptType.REVIEW:
        return _run_review_attempt(
            store=store,
            task=task,
            attempt_id=attempt_id,
            attempt_index=attempt_index,
            adapter=adapter,
            workspace_record=workspace_record,
            per_criterion_timeout_seconds=per_criterion_timeout_seconds,
            evidence_store=evidence_store,
            prior_attempts=prior_attempts,
        )

    attempt_started = time.time()
    per_criterion_results: list[dict[str, Any]] = []
    task_blockers: list[str] = []
    evidence_manifest = EvidenceManifest(attempt_id=attempt_id)
    any_must_pass_present = False
    all_must_pass_passed = True
    first_failure_packet: FailureEvidencePacket | None = None
    env_meta = workspace_record.metadata.get("environment") if isinstance(workspace_record.metadata, dict) else None
    if isinstance(env_meta, dict) and env_meta.get("status") == "failed":
        failure_class = _normalize_failure_class(env_meta.get("failure_class"), default=FailureClass.RETRYABLE)
        first_failure_packet = FailureEvidencePacket(
            failure_class=failure_class,
            attempt_id=attempt_id,
            task_id=task["task_id"],
            criterion=criteria[0].get("criterion_id", "environment") if criteria else "environment",
            evidence_refs=[env_meta.get("metadata_path", "")],
            error_message=env_meta.get("failure_reason", "environment provisioning failed"),
            root_cause_hypothesis=env_meta.get("failure_reason", "environment provisioning failed"),
            prior_attempts=[a.attempt_id for a in prior_attempts],
            failing_command="environment_provision",
            recent_lane=attempt_type.value,
            hints=(
                ["environment_hint", "tooling_hint"]
                if env_meta.get("failure_class") == "environment_block" and env_meta.get("missing_executables")
                else (["environment_hint"] if env_meta.get("failure_class") == "environment_block" else [])
            ),
            metadata={"environment": env_meta},
        )
        packet_path = evidence_store.store_evidence_packet(first_failure_packet)
        manifest_path = evidence_store.store_manifest(evidence_manifest)
        task_blockers.append(first_failure_packet.error_message or "environment provisioning failed")
        attempt_record = TaskAttemptRecord(
            attempt_id=attempt_id,
            task_id=task["task_id"],
            attempt_index=attempt_index,
            backend_id=adapter.backend_id(),
            status=AdapterStatus.FAILED.value,
            winning_attempt=False,
            workspace_ref=workspace_record.path or "",
            workspace_id=workspace_record.workspace_id or "",
            workspace_mode=workspace_record.lineage_type.value,
            parent_attempt_id=prior_attempts[-1].attempt_id if prior_attempts else "",
            derived_from_attempt_ids=[a.attempt_id for a in prior_attempts[-1:]],
            started_at=attempt_started,
            finished_at=time.time(),
            blockers=task_blockers,
            error=first_failure_packet.error_message or "",
            failure_packet_ref=str(packet_path),
            result_evidence_refs=[str(manifest_path)],
            attempt_type=attempt_type.value,
            metadata={
                "criteria_results": [],
                "attempt_type": attempt_type.value,
                "workspace": workspace_record.to_dict(),
                "environment": env_meta,
                "review_required": task.get("review_required", False),
            },
        )
        store.write_attempt(attempt_record)
        return {"attempt_record": attempt_record, "criteria_results": [], "failure_packet": first_failure_packet}

    prior_attempt_records = [
        record for record in store.attempts_for_task(task["task_id"])
        if record.attempt_id != attempt_id
    ]
    prior_evidence_refs: list[str] = []
    for prior in prior_attempt_records:
        prior_evidence_refs.extend(prior.result_evidence_refs)
        if prior.failure_packet_ref:
            prior_evidence_refs.append(prior.failure_packet_ref)
    run_id = store.read_manifest().run_id if store.read_manifest() is not None else "unknown"
    repo_context = summarize_repo_context(workspace_record.path or os.getcwd(), task)
    repo_summary_ref = persist_repo_summary_artifact(store.run_root, task["task_id"], repo_context)
    repo_context["repo_summary_ref"] = repo_summary_ref
    strategy_memory_ref = ensure_strategy_memory_artifact(
        store.run_root,
        task["task_id"],
        run_id=run_id,
        prior_attempts=prior_attempt_records,
    )
    strategy_memory = load_strategy_memory_artifact(store.run_root, strategy_memory_ref)
    execution_packet = build_execution_packet(
        run_id=run_id,
        task=task,
        attempt_id=attempt_id,
        attempt_series=attempt_index + 1,
        workspace_root=workspace_record.path or os.getcwd(),
        prior_attempts=prior_attempt_records,
        prior_evidence_refs=prior_evidence_refs,
        strategy_memory_ref=strategy_memory_ref,
        strategy_memory=strategy_memory,
        repo_context=repo_context,
    )
    retry_admission = execution_packet.history.get("retry_admission", {}) if isinstance(execution_packet.history, dict) else {}
    if attempt_type != AttemptType.BUILD and retry_admission.get("admitted") is False:
        required_deltas = [str(delta) for delta in retry_admission.get("required_deltas", []) if str(delta)]
        blocked_reason = "retry admission rejected: required delta for retry not yet satisfied"
        if required_deltas:
            blocked_reason = f"{blocked_reason} ({'; '.join(required_deltas)})"
        failure_packet = FailureEvidencePacket(
            failure_class=FailureClass.STUCK_OR_REPEATING,
            attempt_id=attempt_id,
            task_id=task["task_id"],
            criterion="retry_admission",
            evidence_refs=list(prior_evidence_refs),
            error_message=blocked_reason,
            root_cause_hypothesis="required_delta_for_retry_not_structurally_satisfied",
            prior_attempts=[a.attempt_id for a in prior_attempts],
            failing_command="retry_admission",
            recent_lane=attempt_type.value,
            hints=["repeat_hint"],
            metadata={"retry_admission": retry_admission},
        )
        packet_path = evidence_store.store_evidence_packet(failure_packet)
        manifest_path = evidence_store.store_manifest(EvidenceManifest(attempt_id=attempt_id))
        attempt_record = TaskAttemptRecord(
            attempt_id=attempt_id,
            task_id=task["task_id"],
            attempt_index=attempt_index,
            backend_id=adapter.backend_id(),
            status=AdapterStatus.FAILED.value,
            winning_attempt=False,
            workspace_ref=workspace_record.path or "",
            workspace_id=workspace_record.workspace_id or "",
            workspace_mode=workspace_record.lineage_type.value,
            parent_attempt_id=prior_attempts[-1].attempt_id if prior_attempts else "",
            derived_from_attempt_ids=[a.attempt_id for a in prior_attempts[-1:]],
            started_at=attempt_started,
            finished_at=time.time(),
            blockers=[blocked_reason],
            error=blocked_reason,
            failure_packet_ref=str(packet_path),
            result_evidence_refs=[str(manifest_path)],
            attempt_type=attempt_type.value,
            metadata={
                "criteria_results": [],
                "attempt_type": attempt_type.value,
                "workspace": workspace_record.to_dict(),
                "review_required": task.get("review_required", False),
                "execution_packet": execution_packet.to_dict(),
                "retry_admission": retry_admission,
            },
        )
        store.write_attempt(attempt_record)
        return {"attempt_record": attempt_record, "criteria_results": [], "failure_packet": failure_packet}

    for crit in criteria:
        crit_id = crit.get("criterion_id", "")
        crit_class = crit.get("criterion_class", "must_pass")
        triple = crit.get("triple", {})
        cmd = triple.get("verification_command", "")
        expected = triple.get("expected_output", "")
        build_target = triple.get("build_target", "")

        if crit_class == "must_pass":
            any_must_pass_present = True

        store.append_event("criterion_dispatched", task_id=task["task_id"], attempt_id=attempt_id, payload={
            "criterion_id": crit_id,
            "verification_command": cmd[:200],
            "expected_output": expected[:200],
            "criterion_class": crit_class,
            "attempt_type": attempt_type.value,
        })

        retry_guardrails = execution_packet.history.get("retry_guardrails", {}) if isinstance(execution_packet.history, dict) else {}
        prompt_parts = [
            f"Task: {execution_packet.task['goal']}",
            f"Criterion: {crit_id}",
            f"Attempt type: {attempt_type.value}",
            f"Relevant files: {', '.join(execution_packet.repo_context.get('relevant_files', [])) or 'none'}",
        ]
        if retry_guardrails.get("must_materially_differ"):
            prompt_parts.append("Rejected strategies exist. You must use a materially different strategy than the rejected attempt(s).")
            required_deltas = retry_guardrails.get("required_deltas", [])
            if required_deltas:
                prompt_parts.append(f"Required delta(s): {', '.join(required_deltas)}")

        prompt_text = "\n".join(prompt_parts)
        spec = AdapterRunSpec(
            spec_id=f"{task['task_id']}.{crit_id}",
            prompt=prompt_text,
            cwd=workspace_record.path or os.getcwd(),
            timeout_seconds=per_criterion_timeout_seconds,
            required_capabilities={Capability.SHELL_EXEC},
            metadata={
                "command": cmd,
                "expected_output": expected,
                "build_target": build_target,
                "task_id": task["task_id"],
                "criterion_id": crit_id,
                "attempt_type": attempt_type.value,
                "attempt_id": attempt_id,
                "workspace_path": workspace_record.path,
                "workspace_mode": workspace_record.lineage_type.value,
                "environment": workspace_record.metadata.get("environment", {}),
                "execution_packet": execution_packet.to_dict(),
            },
        )

        try:
            handle = adapter.spawn(spec)
            result = adapter.collect(handle)
        except FileNotFoundError as e:
            result = None
            error = f"adapter raised: {e}"
            status = AdapterStatus.FAILED
            summary = ""
            artifacts: list[str] = []
        except Exception as e:
            result = None
            error = f"adapter raised: {e}"
            status = AdapterStatus.FAILED
            summary = ""
            artifacts = []
        else:
            status = result.status
            error = result.error
            summary = result.summary
            artifacts = list(result.artifact_paths)

        bugfix_protocol_record = _extract_bugfix_protocol_record(artifacts) if is_bugfix_task(task) else None
        bugfix_protocol_ref = (
            _persist_reproduction_not_possible_record(store, task["task_id"], attempt_id, bugfix_protocol_record)
            if bugfix_protocol_record is not None else ""
        )

        verdict = "pass" if status == AdapterStatus.COMPLETE else "fail"
        target_checked = False
        target_exists = None
        if verdict == "pass" and build_target:
            looks_like_path = "/" in build_target or any(build_target.endswith(ext) for ext in (".py", ".js", ".ts", ".md", ".rs", ".go", ".java", ".cpp", ".c", ".h"))
            if looks_like_path:
                target_checked = True
                abs_target = build_target if os.path.isabs(build_target) else os.path.join(workspace_record.path or os.getcwd(), build_target)
                target_exists = os.path.exists(abs_target)
                if not target_exists:
                    verdict = "fail"
                    error = error or f"build_target missing: {build_target}"
                    store.append_event("build_target_missing", task_id=task["task_id"], attempt_id=attempt_id, payload={"criterion_id": crit_id, "build_target": build_target, "expected_at": abs_target})

        if crit_class == "must_pass" and verdict != "pass":
            all_must_pass_passed = False
            failure_packet = _classify_failure(
                attempt_id=attempt_id,
                task_id=task["task_id"],
                criterion_id=crit_id,
                cmd=cmd,
                build_target=build_target,
                error=error,
                prior_attempts=prior_attempts,
                attempt_type=attempt_type,
                adapter_status=status,
                artifact_paths=artifacts,
                build_target_exists=target_exists,
            )
            packet_path = evidence_store.store_evidence_packet(failure_packet)
            first_failure_packet = first_failure_packet or failure_packet
            task_blockers.append(f"criterion {crit_id} failed: {error or 'no detail'}")
            store.append_event("failure_packet_created", task_id=task["task_id"], attempt_id=attempt_id, payload={
                "failure_class": failure_packet.failure_class.value,
                "packet_path": str(packet_path),
                "signature": failure_packet.signature,
            })
        else:
            evidence_manifest.set_criterion_result(crit_id, verdict == "pass")

        prompt_audit = PromptAuditRecord(
            audit_id=f"audit-{attempt_id}-{crit_id}",
            run_id=execution_packet.run_id,
            task_id=task["task_id"],
            attempt_id=attempt_id,
            attempt_type=attempt_type.value,
            prompt_policy={
                "family": execution_packet.policy_snapshot.get("prompt_family", ""),
                "version": "phase-4",
                "role": attempt_type.value,
                "model_route": execution_packet.policy_snapshot.get("model_route", "default"),
                "tool_scope": list(execution_packet.policy_snapshot.get("tool_scope", [])),
            },
            prompt_instantiation={
                "packet_ref": None,
                "included_files": list(execution_packet.repo_context.get("relevant_files", [])),
                "included_evidence_refs": list(execution_packet.history.get("prior_evidence_refs", [])),
                "instructions_hash": hashlib.sha256(prompt_text.encode("utf-8")).hexdigest(),
                "rendered_prompt": prompt_text,
                "criterion_id": crit_id,
            },
            model_execution={
                "provider": adapter.backend_id(),
                "model": execution_packet.policy_snapshot.get("model_route", "default"),
                "status": status.value,
                "started_at": attempt_started,
                "finished_at": time.time(),
            },
            result={
                "outcome": status.value,
                "response_ref": None,
                "files_touched": list(artifacts),
                "commands_run": [cmd] if cmd else [],
                "summary": summary,
                "error": error,
            },
        )
        prompt_audit_ref = persist_prompt_audit_record(store.run_root, task["task_id"], f"{attempt_id}-{crit_id}", prompt_audit.to_dict())
        per_criterion_results.append({
            "criterion_id": crit_id,
            "criterion_class": crit_class,
            "verdict": verdict,
            "adapter_status": status.value,
            "summary": summary,
            "error": error,
            "build_target_checked": target_checked,
            "build_target_exists": target_exists,
            "prompt_audit_ref": prompt_audit_ref,
        })
        for artifact in artifacts:
            evidence_manifest.add_artifact(artifact)
        event_type = "criterion_passed" if verdict == "pass" else "criterion_failed"
        store.append_event(event_type, task_id=task["task_id"], attempt_id=attempt_id, payload={"criterion_id": crit_id, "adapter_status": status.value, "error": (error or "")[:300]})

    if not any_must_pass_present:
        all_must_pass_passed = False
        task_blockers.append("no must_pass criteria")

    final_status = AdapterStatus.COMPLETE if all_must_pass_passed and any_must_pass_present else AdapterStatus.FAILED
    manifest_path = evidence_store.store_manifest(evidence_manifest)
    review_policy = normalize_review_policy(task)
    validation_policy = build_validation_policy(task)
    validator_chain = ValidatorChainArtifact(
        artifact_id=f"validator-{attempt_id}",
        run_id=execution_packet.run_id,
        task_id=task["task_id"],
        attempt_id=attempt_id,
        review_policy=review_policy,
        validation_policy=validation_policy,
        results={
            "required_commands": [{"command": cmd, "status": ("passed" if item["verdict"] == "pass" else "failed")} for cmd, item in zip(validation_policy["required_commands"], per_criterion_results)],
            "must_pass": [item for item in per_criterion_results if item["criterion_class"] == "must_pass"],
            "informational": [item for item in per_criterion_results if item["criterion_class"] != "must_pass"],
            "manifest_ref": str(manifest_path),
        },
    )
    validator_chain_ref = persist_validator_chain_artifact(store.run_root, task["task_id"], attempt_id, validator_chain.to_dict())
    bugfix_state = execution_packet.history.get("current_bugfix_state", "") if isinstance(execution_packet.history, dict) else ""
    if is_bugfix_task(task):
        has_bugfix_protocol = bugfix_protocol_record is not None
        prior_bugfix_state = execution_packet.history.get("current_bugfix_state")
        if final_status == AdapterStatus.COMPLETE and prior_bugfix_state not in {"reproduced", "reproduction_not_possible", "verified"} and not has_bugfix_protocol:
            final_status = AdapterStatus.FAILED
            task_blockers.append("bugfix success rejected: reproduction evidence or justified reproduction_not_possible record required")
            bugfix_state = "investigating"
            if first_failure_packet is None:
                first_failure_packet = FailureEvidencePacket(
                    failure_class=FailureClass.RETRYABLE,
                    attempt_id=attempt_id,
                    task_id=task["task_id"],
                    criterion="bugfix_protocol",
                    evidence_refs=[str(manifest_path)],
                    error_message="reproduction_evidence_required",
                    root_cause_hypothesis="bugfix_protocol_requires_reproduction_before_fixing",
                    prior_attempts=[a.attempt_id for a in prior_attempts],
                    failing_command="bugfix_protocol",
                    recent_lane=attempt_type.value,
                    hints=["test_failure_hint"],
                )
                evidence_store.store_evidence_packet(first_failure_packet)
        elif final_status == AdapterStatus.COMPLETE:
            bugfix_state = "reproduction_not_possible" if has_bugfix_protocol or prior_bugfix_state == "reproduction_not_possible" else "verified"
        else:
            bugfix_state = "reproduced"
    execution_result = StructuredExecutionResult(
        run_id=execution_packet.run_id,
        task_id=task["task_id"],
        status="task_succeeded" if final_status == AdapterStatus.COMPLETE else "task_failed",
        terminal=True,
        terminal_reason="validation_passed" if final_status == AdapterStatus.COMPLETE else "validation_failed",
        recommended_transition="accept" if final_status == AdapterStatus.COMPLETE else "repair",
        attempt_count=attempt_index + 1,
        final_attempt_id=attempt_id,
        current_bugfix_state=bugfix_state,
        summary="; ".join(f"{item['criterion_id']}={item['verdict']}" for item in per_criterion_results),
        artifact_refs={
            "validator_report": str(manifest_path),
            "validator_chain": validator_chain_ref,
            "prompt_audits": [item["prompt_audit_ref"] for item in per_criterion_results if item.get("prompt_audit_ref")],
            "failure_packet": first_failure_packet.to_dict() if first_failure_packet else None,
            "reproduction_not_possible_record": bugfix_protocol_ref or None,
        },
        metrics={
            "criterion_count": len(per_criterion_results),
            "must_pass_present": any_must_pass_present,
        },
    )
    attempt_record = TaskAttemptRecord(
        attempt_id=attempt_id,
        task_id=task["task_id"],
        attempt_index=attempt_index,
        backend_id=adapter.backend_id(),
        status=final_status.value,
        winning_attempt=final_status == AdapterStatus.COMPLETE,
        workspace_ref=workspace_record.path or "",
        workspace_id=workspace_record.workspace_id or "",
        workspace_mode=workspace_record.lineage_type.value,
        parent_attempt_id=prior_attempts[-1].attempt_id if prior_attempts else "",
        derived_from_attempt_ids=[a.attempt_id for a in prior_attempts[-1:]],
        started_at=attempt_started,
        finished_at=time.time(),
        blockers=task_blockers,
        error=first_failure_packet.error_message if first_failure_packet and first_failure_packet.error_message else "",
        failure_packet_ref=str(evidence_store._run_dir(task["task_id"]) / f"{attempt_id}_evidence.json") if first_failure_packet else "",
        result_evidence_refs=[str(manifest_path)],
        attempt_type=attempt_type.value,
        metadata={
            "criteria_results": per_criterion_results,
            "attempt_type": attempt_type.value,
            "workspace": workspace_record.to_dict(),
            "review_required": review_policy["required"],
            "review_policy": review_policy,
            "validation_policy": validation_policy,
            "execution_packet": execution_packet.to_dict(),
            "structured_execution_result": execution_result.to_dict(),
            "bugfix_protocol_record": bugfix_protocol_record,
            "bugfix_protocol_ref": bugfix_protocol_ref,
        },
    )
    store.write_attempt(attempt_record)
    _update_strategy_memory_after_attempt(
        store=store,
        task=task,
        strategy_memory_ref=strategy_memory_ref,
        execution_packet=execution_packet,
        attempt_id=attempt_id,
        attempt_type=attempt_type.value,
        final_status=final_status,
        failure_packet=first_failure_packet,
        manifest_path=str(manifest_path),
        per_criterion_results=per_criterion_results,
        bugfix_protocol_record=bugfix_protocol_record,
        bugfix_protocol_ref=bugfix_protocol_ref,
    )
    return {
        "attempt_record": attempt_record,
        "criteria_results": per_criterion_results,
        "failure_packet": first_failure_packet,
    }


def _run_review_attempt(
    *,
    store: RunStore,
    task: dict[str, Any],
    attempt_id: str,
    attempt_index: int,
    adapter: BackendAdapter,
    workspace_record: WorkspaceRecord,
    per_criterion_timeout_seconds: int,
    evidence_store: EvidenceStore,
    prior_attempts: list[Any],
) -> dict[str, Any]:
    attempt_started = time.time()
    candidate = next((a for a in reversed(prior_attempts) if getattr(a, "attempt_type", "") != AttemptType.REVIEW.value), None)
    candidate_attempt_id = candidate.attempt_id if candidate is not None else ""
    prior_attempt_records = [
        record for record in store.attempts_for_task(task["task_id"])
        if record.attempt_id != attempt_id
    ]
    run_id = store.read_manifest().run_id if store.read_manifest() is not None else "unknown"
    repo_context = summarize_repo_context(workspace_record.path or os.getcwd(), task)
    repo_summary_ref = persist_repo_summary_artifact(store.run_root, task["task_id"], repo_context)
    repo_context["repo_summary_ref"] = repo_summary_ref
    strategy_memory_ref = ensure_strategy_memory_artifact(
        store.run_root,
        task["task_id"],
        run_id=run_id,
        prior_attempts=prior_attempt_records,
    )
    strategy_memory = load_strategy_memory_artifact(store.run_root, strategy_memory_ref)
    review_packet = build_execution_packet(
        run_id=run_id,
        task=task,
        attempt_id=attempt_id,
        attempt_series=attempt_index + 1,
        workspace_root=workspace_record.path or os.getcwd(),
        prior_attempts=prior_attempt_records,
        prior_evidence_refs=[ref for record in prior_attempt_records for ref in ([*record.result_evidence_refs] + ([record.failure_packet_ref] if record.failure_packet_ref else []))],
        strategy_memory_ref=strategy_memory_ref,
        strategy_memory=strategy_memory,
        repo_context=repo_context,
    )
    review_prompt = (
        f"Review task: {review_packet.task['goal']}\n"
        f"Candidate attempt: {candidate_attempt_id}\n"
        f"Relevant files: {', '.join(review_packet.repo_context.get('relevant_files', [])) or 'none'}"
    )
    review_spec = AdapterRunSpec(
        spec_id=f"{task['task_id']}.review",
        prompt=review_prompt,
        cwd=workspace_record.path or os.getcwd(),
        timeout_seconds=per_criterion_timeout_seconds,
        required_capabilities=set(),
        metadata={
            "task_id": task["task_id"],
            "attempt_type": AttemptType.REVIEW.value,
            "attempt_id": attempt_id,
            "workspace_path": workspace_record.path,
            "candidate_attempt_id": candidate_attempt_id,
            "review_contract": "crucible.v5.4.review.json",
            "execution_packet": review_packet.to_dict(),
        },
    )
    try:
        handle = adapter.spawn(review_spec)
        result = adapter.collect(handle)
    except Exception as e:
        result = None
        status = AdapterStatus.FAILED
        error = f"review adapter raised: {e}"
        summary = ""
        artifacts = []
    else:
        status = result.status
        error = result.error
        summary = result.summary
        artifacts = list(result.artifact_paths)

    manifest = EvidenceManifest(attempt_id=attempt_id)
    for artifact in artifacts:
        manifest.add_artifact(artifact)
    review_payload = _load_contract_artifact(artifacts, "review")
    review_contract_ok = _review_contract_satisfied(review_payload)
    manifest.review_verdict = review_payload.get("verdict") if isinstance(review_payload, dict) else None
    if not review_contract_ok:
        status = AdapterStatus.FAILED
        error = error or "review artifact missing or invalid"
        manifest.unresolved_risks.append("review_contract_invalid")
    manifest_path = evidence_store.store_manifest(manifest)
    review_policy = normalize_review_policy(task)
    validation_policy = build_validation_policy(task)
    prompt_audit = PromptAuditRecord(
        audit_id=f"audit-{attempt_id}",
        run_id=review_packet.run_id,
        task_id=task["task_id"],
        attempt_id=attempt_id,
        attempt_type=AttemptType.REVIEW.value,
        prompt_policy={
            "family": review_packet.policy_snapshot.get("prompt_family", ""),
            "version": "phase-4",
            "role": AttemptType.REVIEW.value,
            "model_route": review_packet.policy_snapshot.get("model_route", "default"),
            "tool_scope": list(review_packet.policy_snapshot.get("tool_scope", [])),
        },
        prompt_instantiation={
            "packet_ref": None,
            "included_files": list(review_packet.repo_context.get("relevant_files", [])),
            "included_evidence_refs": list(review_packet.history.get("prior_evidence_refs", [])),
            "instructions_hash": hashlib.sha256(review_prompt.encode("utf-8")).hexdigest(),
            "rendered_prompt": review_prompt,
            "candidate_attempt_id": candidate_attempt_id,
        },
        model_execution={
            "provider": adapter.backend_id(),
            "model": review_packet.policy_snapshot.get("model_route", "default"),
            "status": status.value,
            "started_at": attempt_started,
            "finished_at": time.time(),
        },
        result={
            "outcome": status.value,
            "response_ref": None,
            "files_touched": list(artifacts),
            "commands_run": [],
            "summary": summary,
            "error": error,
        },
    )
    prompt_audit_ref = persist_prompt_audit_record(store.run_root, task["task_id"], attempt_id, prompt_audit.to_dict())
    validator_chain = ValidatorChainArtifact(
        artifact_id=f"validator-{attempt_id}",
        run_id=review_packet.run_id,
        task_id=task["task_id"],
        attempt_id=attempt_id,
        review_policy=review_policy,
        validation_policy=validation_policy,
        results={
            "required_commands": [{"command": command, "status": "pending_review"} for command in validation_policy["required_commands"]],
            "must_pass": list(validation_policy["must_pass"]),
            "informational": list(validation_policy["informational"]),
            "manifest_ref": str(manifest_path),
            "review_payload": review_payload,
        },
    )
    validator_chain_ref = persist_validator_chain_artifact(store.run_root, task["task_id"], attempt_id, validator_chain.to_dict())
    review_bugfix_state = ""
    if is_bugfix_task(task):
        review_bugfix_state = "verified" if status == AdapterStatus.COMPLETE and review_contract_ok else str(review_packet.history.get("current_bugfix_state") or "reproduced")
    execution_result = StructuredExecutionResult(
        run_id=review_packet.run_id,
        task_id=task["task_id"],
        status="task_succeeded" if status == AdapterStatus.COMPLETE and review_contract_ok else "task_failed",
        terminal=True,
        terminal_reason="review_passed" if status == AdapterStatus.COMPLETE and review_contract_ok else "review_failed",
        recommended_transition="accept" if status == AdapterStatus.COMPLETE and review_contract_ok else "repair",
        attempt_count=attempt_index + 1,
        final_attempt_id=attempt_id,
        current_bugfix_state=review_bugfix_state,
        summary=summary,
        artifact_refs={
            "validator_report": str(manifest_path),
            "validator_chain": validator_chain_ref,
            "prompt_audit": prompt_audit_ref,
        },
        metrics={"review_contract_valid": review_contract_ok},
    )
    attempt_record = TaskAttemptRecord(
        attempt_id=attempt_id,
        task_id=task["task_id"],
        attempt_index=attempt_index,
        backend_id=adapter.backend_id(),
        status=status.value,
        winning_attempt=False,
        workspace_ref=workspace_record.path or "",
        workspace_id=workspace_record.workspace_id or "",
        workspace_mode=workspace_record.lineage_type.value,
        parent_attempt_id=candidate_attempt_id,
        derived_from_attempt_ids=[candidate_attempt_id] if candidate_attempt_id else [],
        started_at=attempt_started,
        finished_at=time.time(),
        blockers=[error] if error else [],
        error=error,
        result_evidence_refs=[str(manifest_path)],
        attempt_type=AttemptType.REVIEW.value,
        metadata={
            "summary": summary,
            "review_payload": review_payload,
            "candidate_attempt_id": candidate_attempt_id,
            "review_contract_valid": review_contract_ok,
            "review_policy": review_policy,
            "validation_policy": validation_policy,
            "execution_packet": review_packet.to_dict(),
            "structured_execution_result": execution_result.to_dict(),
        },
    )
    store.write_attempt(attempt_record)
    _update_strategy_memory_after_review(
        store=store,
        task=task,
        strategy_memory_ref=strategy_memory_ref,
        review_packet=review_packet,
        attempt_id=attempt_id,
        review_status=status,
        review_contract_ok=review_contract_ok,
        manifest_path=str(manifest_path),
        review_payload=review_payload,
        candidate_attempt_id=candidate_attempt_id,
    )
    return {
        "attempt_record": attempt_record,
        "criteria_results": [{"review_contract_valid": review_contract_ok, "candidate_attempt_id": candidate_attempt_id}],
        "failure_packet": None,
    }


def _update_strategy_memory_after_attempt(
    *,
    store: RunStore,
    task: dict[str, Any],
    strategy_memory_ref: str,
    execution_packet: Any,
    attempt_id: str,
    attempt_type: str,
    final_status: AdapterStatus,
    failure_packet: FailureEvidencePacket | None,
    manifest_path: str,
    per_criterion_results: list[dict[str, Any]],
    bugfix_protocol_record: dict[str, Any] | None,
    bugfix_protocol_ref: str,
) -> None:
    memory = load_strategy_memory_artifact(store.run_root, strategy_memory_ref)
    memory.setdefault("entries", [])
    memory.setdefault("current_hypotheses", [])
    memory.setdefault("reproduction", {"status": "missing", "evidence_refs": [], "summary": "", "reproduction_not_possible": None})
    if is_bugfix_task(task):
        if final_status == AdapterStatus.COMPLETE:
            if bugfix_protocol_record is not None:
                memory["current_bugfix_state"] = "reproduction_not_possible"
                memory["reproduction"] = {
                    "status": "reproduction_not_possible",
                    "evidence_refs": [ref for ref in [manifest_path, bugfix_protocol_ref] if ref],
                    "summary": str(bugfix_protocol_record.get("why") or ""),
                    "reproduction_not_possible": dict(bugfix_protocol_record),
                }
            elif memory.get("reproduction", {}).get("status") not in {"captured", "reproduction_not_possible"}:
                memory["current_bugfix_state"] = "investigating"
                memory.setdefault("entries", []).append({
                    "attempt_id": attempt_id,
                    "attempt_type": attempt_type,
                    "strategy": "success_without_reproduction_evidence",
                    "outcome": "rejected",
                    "reason": "reproduction_evidence_required",
                    "do_not_repeat_without_change": True,
                    "required_delta_for_retry": "capture durable reproduction evidence or persist a justified reproduction_not_possible decision before claiming success",
                    "evidence_refs": [manifest_path],
                })
            else:
                memory["current_bugfix_state"] = "verified"
        else:
            if failure_packet is not None and failure_packet.root_cause_hypothesis == "bugfix_protocol_requires_reproduction_before_fixing":
                memory["current_bugfix_state"] = "investigating"
            else:
                memory["current_bugfix_state"] = "reproduced"
                reproduction = memory.setdefault("reproduction", {})
                reproduction["status"] = "captured"
                reproduction["summary"] = "pre-fix failure captured"
                evidence_refs = list(reproduction.get("evidence_refs") or [])
                if failure_packet is not None:
                    evidence_refs.extend([ref for ref in [manifest_path, *failure_packet.evidence_refs] if ref])
                else:
                    evidence_refs.append(manifest_path)
                reproduction["evidence_refs"] = sorted(set(evidence_refs))

    if final_status != AdapterStatus.COMPLETE:
        entry = {
            "attempt_id": attempt_id,
            "attempt_type": attempt_type,
            "strategy": f"{attempt_type}:{execution_packet.task.get('goal', '')}",
            "outcome": "rejected",
            "reason": "validation_failed",
            "do_not_repeat_without_change": True,
            "required_delta_for_retry": "materially different strategy with new evidence or code path",
            "evidence_refs": [manifest_path] + ([failure_packet.failing_command] if failure_packet and failure_packet.failing_command else []),
        }
        memory["entries"].append(entry)
        if failure_packet is not None and failure_packet.root_cause_hypothesis:
            hypothesis = str(failure_packet.root_cause_hypothesis)
            if hypothesis not in memory["current_hypotheses"]:
                memory["current_hypotheses"].append(hypothesis)

    persist_strategy_memory_artifact(store.run_root, strategy_memory_ref, memory)


def _update_strategy_memory_after_review(
    *,
    store: RunStore,
    task: dict[str, Any],
    strategy_memory_ref: str,
    review_packet: Any,
    attempt_id: str,
    review_status: AdapterStatus,
    review_contract_ok: bool,
    manifest_path: str,
    review_payload: dict[str, Any] | None,
    candidate_attempt_id: str,
) -> None:
    memory = load_strategy_memory_artifact(store.run_root, strategy_memory_ref)
    memory.setdefault("entries", [])
    if review_status == AdapterStatus.COMPLETE and review_contract_ok:
        if is_bugfix_task(task) and memory.get("reproduction", {}).get("status") in {"captured", "reproduction_not_possible"}:
            memory["current_bugfix_state"] = "verified"
        persist_strategy_memory_artifact(store.run_root, strategy_memory_ref, memory)
        return
    memory["entries"].append({
        "attempt_id": attempt_id,
        "attempt_type": "review",
        "strategy": f"review:{review_packet.task.get('goal', '')}",
        "outcome": "rejected",
        "reason": "review_rejected",
        "do_not_repeat_without_change": True,
        "required_delta_for_retry": "address reviewer rejection with materially different strategy",
        "evidence_refs": [manifest_path, candidate_attempt_id],
    })
    persist_strategy_memory_artifact(store.run_root, strategy_memory_ref, memory)


def _load_contract_artifact(artifact_paths: list[str], contract_type: str) -> dict[str, Any] | None:
    expected_name = f"crucible_{contract_type}.json"
    for artifact in artifact_paths:
        path = Path(artifact)
        if path.name != expected_name or not path.exists():
            continue
        try:
            data = json.loads(path.read_text())
        except json.JSONDecodeError:
            return None
        return data if isinstance(data, dict) else None
    return None


def _extract_bugfix_protocol_record(artifact_paths: list[str]) -> dict[str, Any] | None:
    payload = _load_contract_artifact(artifact_paths, "bugfix")
    if not isinstance(payload, dict):
        return None
    if payload.get("state") != "reproduction_not_possible":
        return None
    required = {"why", "approaches_tried", "surrogate_evidence", "post_fix_validation"}
    if not required.issubset(payload):
        return None
    if not all(isinstance(payload.get(field), list) for field in ("approaches_tried", "surrogate_evidence", "post_fix_validation")):
        return None
    return payload


def _persist_reproduction_not_possible_record(store: RunStore, task_id: str, attempt_id: str, payload: dict[str, Any]) -> str:
    path = Path(store.run_root) / "artifacts" / task_id / f"reproduction-not-possible-{attempt_id}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True))
    return str(path.relative_to(Path(store.run_root)))


def _review_contract_satisfied(payload: dict[str, Any] | None) -> bool:
    if not isinstance(payload, dict):
        return False
    required = {"verdict", "criterion_coverage", "evidence_sufficient", "unresolved_risks"}
    if not required.issubset(payload):
        return False
    if payload["verdict"] not in {"accept", "reject"}:
        return False
    if not isinstance(payload["criterion_coverage"], dict) or not payload["criterion_coverage"]:
        return False
    if not all(isinstance(k, str) and isinstance(v, bool) for k, v in payload["criterion_coverage"].items()):
        return False
    if not isinstance(payload["evidence_sufficient"], bool):
        return False
    if not isinstance(payload["unresolved_risks"], list) or not all(isinstance(item, str) for item in payload["unresolved_risks"]):
        return False
    return True



def _resolve_review_decision(
    *,
    task: dict[str, Any],
    review_attempt: Any,
    review_attempt_record: TaskAttemptRecord,
    criteria_results: list[dict[str, Any]],
    evidence_store: EvidenceStore,
    prior_attempts: list[Any],
) -> dict[str, Any]:
    payload = (review_attempt_record.metadata or {}).get("review_payload") or {}
    accepted_attempt_id = review_attempt_record.parent_attempt_id
    criterion_ids = {c.get("criterion_id", "") for c in task.get("criteria", []) if c.get("criterion_id")}
    coverage = payload.get("criterion_coverage", {}) if isinstance(payload, dict) else {}
    coverage_complete = criterion_ids.issubset(set(coverage)) and all(coverage.get(cid) is True for cid in criterion_ids)
    evidence_sufficient = bool(payload.get("evidence_sufficient"))
    unresolved_risks = list(payload.get("unresolved_risks", [])) if isinstance(payload, dict) else []
    verdict = payload.get("verdict") if isinstance(payload, dict) else None

    if review_attempt_record.status == AdapterStatus.COMPLETE.value and verdict == "accept" and coverage_complete and evidence_sufficient:
        manifest = evidence_store.load_manifest(accepted_attempt_id)
        if manifest is not None:
            manifest.review_verdict = "accept"
            evidence_store.store_manifest(manifest)
        for prior in reversed(prior_attempts):
            if getattr(prior, "attempt_id", "") == accepted_attempt_id:
                prior.state = prior.state.VALIDATED_PASS
                break
        return {
            "verdict": "accept",
            "accepted_attempt_id": accepted_attempt_id,
            "next_action": NextAction.COMPLETE.value,
            "rejection_type": "",
            "failure_packet": None,
        }

    rejection_type = "review_rejected"
    if review_attempt_record.status != AdapterStatus.COMPLETE.value:
        rejection_type = "review_execution_failed"
    elif verdict not in {"accept", "reject"}:
        rejection_type = "invalid_review_contract"
    elif not coverage_complete:
        rejection_type = "incomplete_criterion_coverage"
    elif not evidence_sufficient:
        rejection_type = "missing_causal_explanation"
    elif unresolved_risks:
        rejection_type = "superficial_fix"

    failure_packet = FailureEvidencePacket(
        failure_class=FailureClass.RETRYABLE,
        attempt_id=review_attempt.attempt_id,
        task_id=task["task_id"],
        criterion="review_gate",
        evidence_refs=review_attempt_record.result_evidence_refs,
        error_message=rejection_type,
        root_cause_hypothesis=rejection_type,
        prior_attempts=[a.attempt_id for a in prior_attempts],
        failing_command="review_gate",
        recent_lane=AttemptType.REVIEW.value,
        metadata={"rejection_type": rejection_type, "candidate_attempt_id": accepted_attempt_id},
    )
    evidence_store.store_evidence_packet(failure_packet)
    return {
        "verdict": "reject",
        "accepted_attempt_id": accepted_attempt_id,
        "next_action": NextAction.DEBUG.value if rejection_type == "missing_causal_explanation" else NextAction.REPAIR.value,
        "rejection_type": rejection_type,
        "failure_packet": failure_packet,
    }



def _classify_failure(
    *,
    attempt_id: str,
    task_id: str,
    criterion_id: str,
    cmd: str,
    build_target: str,
    error: str,
    prior_attempts: list[Any],
    attempt_type: AttemptType,
    adapter_status: AdapterStatus,
    artifact_paths: list[str] | None = None,
    build_target_exists: bool | None = None,
) -> FailureEvidencePacket:
    artifact_paths = artifact_paths or []
    structured = _load_contract_artifact(artifact_paths, "failure")
    provisional = FailureEvidencePacket(
        failure_class=FailureClass.RETRYABLE,
        attempt_id=attempt_id,
        task_id=task_id,
        criterion=criterion_id,
        evidence_refs=[build_target] if build_target else [],
        error_message=error,
        prior_attempts=[a.attempt_id for a in prior_attempts],
        failing_command=cmd,
        missing_artifacts=[build_target] if build_target_exists is False and build_target else [],
        recent_lane=attempt_type.value,
    )
    repeated = [
        a for a in prior_attempts
        if getattr(a, "failure_evidence", None)
        and _same_failure_shape(a.failure_evidence, provisional)
    ]
    hints: list[str] = []
    repeated_failure = bool(repeated)
    external_input_required = False
    if isinstance(structured, dict):
        failure_class = _normalize_failure_class(structured.get("failure_class"), default=FailureClass.RETRYABLE)
        root_cause = structured.get("root_cause_hypothesis")
        human_summary = structured.get("human_summary", "")
        machine_action = structured.get("machine_action", failure_class.value)
        hints = [str(h) for h in structured.get("hints", [])]
        repeated_failure = structured.get("repeated_failure", repeated_failure)
        external_input_required = structured.get("external_input_required", False)
    elif repeated:
        failure_class = FailureClass.STUCK_OR_REPEATING
        root_cause = "repeated_failure_signature"
        human_summary = f"stuck_or_repeating; criterion={criterion_id}; repeated failing command"
        machine_action = failure_class.value
        hints = ["repeat_hint"]
    elif adapter_status in {AdapterStatus.TIMED_OUT, AdapterStatus.KILLED}:
        failure_class = FailureClass.RETRYABLE
        root_cause = "executor_interrupted"
        human_summary = f"retryable; criterion={criterion_id}; adapter_status={adapter_status.value}"
        machine_action = failure_class.value
        hints = ["environment_hint"]
    elif build_target_exists is False:
        failure_class = FailureClass.RETRYABLE
        root_cause = "missing_build_target"
        human_summary = f"retryable; criterion={criterion_id}; build_target missing"
        machine_action = failure_class.value
        hints = ["test_failure_hint"]
    elif _looks_like_missing_dependency(error):
        failure_class = FailureClass.RETRYABLE
        root_cause = "dependency_or_project_package_missing"
        human_summary = f"retryable; criterion={criterion_id}; dependency missing"
        machine_action = failure_class.value
        hints = ["dependency_hint", "tooling_hint"]
    elif _looks_like_environment_block(error):
        failure_class = FailureClass.RETRYABLE
        root_cause = "toolchain_or_runtime_unavailable"
        human_summary = f"retryable; criterion={criterion_id}; toolchain unavailable"
        machine_action = failure_class.value
        hints = ["environment_hint", "tooling_hint"]
    elif _looks_like_user_input_needed(error):
        user_input_requirement = _classify_user_input_requirement(error)
        failure_class = FailureClass.NEEDS_USER_INPUT
        root_cause = user_input_requirement["root_cause_hypothesis"]
        human_summary = user_input_requirement["human_summary"] or f"needs_user_input; criterion={criterion_id}"
        machine_action = failure_class.value
        hints = list(user_input_requirement["hints"])
        external_input_required = True
    elif _looks_like_terminal_nonrecoverable(error):
        failure_class = FailureClass.TERMINAL_NONRECOVERABLE
        root_cause = "scope_or_access_terminal_block"
        human_summary = f"terminal_nonrecoverable; criterion={criterion_id}"
        machine_action = failure_class.value
        hints = ["tooling_hint"]
    else:
        failure_class = FailureClass.RETRYABLE
        root_cause = "criteria_not_satisfied"
        human_summary = f"retryable; criterion={criterion_id}"
        machine_action = failure_class.value
        hints = ["test_failure_hint"]
    return FailureEvidencePacket(
        failure_class=failure_class,
        attempt_id=attempt_id,
        task_id=task_id,
        criterion=criterion_id,
        evidence_refs=[build_target] if build_target else [],
        error_message=error,
        root_cause_hypothesis=root_cause,
        human_summary=human_summary,
        machine_action=machine_action,
        prior_attempts=[a.attempt_id for a in prior_attempts],
        failing_command=cmd,
        missing_artifacts=[build_target] if build_target_exists is False and build_target else [],
        recent_lane=attempt_type.value,
        hints=hints,
        repeated_failure=repeated_failure,
        external_input_required=external_input_required,
        metadata={
            "adapter_status": adapter_status.value,
            "structured_failure": structured or {},
            **({"required_user_input": user_input_requirement} if 'user_input_requirement' in locals() else {}),
        },
    )


def _same_failure_shape(previous: FailureEvidencePacket, current: FailureEvidencePacket) -> bool:
    return (
        previous.criterion == current.criterion
        and previous.failing_command == current.failing_command
        and sorted(previous.missing_artifacts) == sorted(current.missing_artifacts)
        and previous.recent_lane == current.recent_lane
    )


def _normalize_failure_class(raw: str | None, *, default: FailureClass) -> FailureClass:
    legacy_map = {
        "ambiguity_block": FailureClass.NEEDS_USER_INPUT,
        "missing_dependency": FailureClass.RETRYABLE,
        "environment_block": FailureClass.RETRYABLE,
        "architecture_mismatch": FailureClass.NEEDS_USER_INPUT,
        "model_limitation": FailureClass.STUCK_OR_REPEATING,
        "validation_failure": FailureClass.RETRYABLE,
        "integration_conflict": FailureClass.RETRYABLE,
        "loop_detected": FailureClass.STUCK_OR_REPEATING,
    }
    if raw in {c.value for c in FailureClass}:
        return FailureClass(raw)
    if raw in legacy_map:
        return legacy_map[raw]
    return default


def _looks_like_missing_dependency(error: str) -> bool:
    text = (error or "").lower()
    markers = [
        "no module named",
        "cannot find module",
        "module not found",
        "could not resolve",
        "missing script",
        "package.json not found",
        "requirements.txt",
    ]
    return any(marker in text for marker in markers)


def _looks_like_environment_block(error: str) -> bool:
    text = (error or "").lower()
    markers = [
        "command not found",
        "executable file not found",
        "no such file or directory",
        "uv: command not found",
        "npm: command not found",
        "node: command not found",
        "python: command not found",
        "pytest: command not found",
    ]
    return any(marker in text for marker in markers)


def _looks_like_user_input_needed(error: str) -> bool:
    text = (error or "").lower()
    markers = [
        "approval required",
        "user confirmation required",
        "provide credential",
        "missing api key",
        "missing token",
        "choose one of",
    ]
    return any(marker in text for marker in markers)


def _classify_user_input_requirement(error: str) -> dict[str, object]:
    text = (error or "").strip()
    lower = text.lower()

    def _extract(patterns: list[str]) -> str | None:
        import re
        for pattern in patterns:
            match = re.search(pattern, text, flags=re.IGNORECASE)
            if match:
                return next((group for group in match.groups() if group), None)
        return None

    secret_target = _extract([
        r"missing api key(?: for)?[ :]+([A-Za-z0-9_./:-]+)",
        r"missing token(?: for)?[ :]+([A-Za-z0-9_./:-]+)",
        r"provide credential(?: for)?[ :]+([A-Za-z0-9_./:-]+)",
        r"missing credential(?: for)?[ :]+([A-Za-z0-9_./:-]+)",
    ])
    approval_target = _extract([
        r"approval required(?: for)?[ :]+([^.;\n]+)",
        r"user confirmation required(?: for)?[ :]+([^.;\n]+)",
    ])
    choice_target = _extract([r"choose one of[ :]+([^.;\n]+)"])

    if any(token in lower for token in ["missing api key", "missing token", "provide credential", "missing credential"]):
        target = secret_target or "missing secret"
        return {
            "type": "credential_required",
            "target": target,
            "source": "error_message",
            "hints": ["credential_hint"],
            "root_cause_hypothesis": "missing_credential_or_secret",
            "human_summary": f"needs_user_input; credential required: {target}",
        }

    if any(token in lower for token in ["approval required", "user confirmation required"]):
        target = approval_target or "approval"
        return {
            "type": "approval_required",
            "target": target,
            "source": "error_message",
            "hints": ["approval_hint"],
            "root_cause_hypothesis": "explicit_approval_required",
            "human_summary": f"needs_user_input; approval required: {target}",
        }

    if "choose one of" in lower:
        target = choice_target or "human decision"
        return {
            "type": "clarification_needed",
            "target": target,
            "source": "error_message",
            "hints": ["ambiguity_hint"],
            "root_cause_hypothesis": "ambiguous_user_decision_required",
            "human_summary": f"needs_user_input; clarification required: {target}",
        }

    return {
        "type": "user_input_required",
        "target": None,
        "source": "error_message",
        "hints": ["ambiguity_hint"],
        "root_cause_hypothesis": "human_input_required",
        "human_summary": "needs_user_input; targeted input required",
    }


def _looks_like_terminal_nonrecoverable(error: str) -> bool:
    text = (error or "").lower()
    markers = [
        "out of scope",
        "permission denied permanently",
        "repository unavailable",
        "access denied",
        "unsupported platform",
        "hard dependency unavailable",
    ]
    return any(marker in text for marker in markers)


def _terminate(
    store: RunStore,
    manifest: RunManifest,
    terminal_status: str,
    start: float,
    *,
    blocked: str = "",
) -> RunSummary:
    canonical_terminal = {
        "failed": RunTerminalStatus.FAILED.value,
        "blocked": RunTerminalStatus.BLOCKED.value,
        "escalated": RunTerminalStatus.ESCALATED.value,
        "cancelled": RunTerminalStatus.CANCELLED.value,
        "complete": RunTerminalStatus.SUCCEEDED.value,
    }.get(terminal_status, terminal_status)
    summary = RunSummary(
        run_id=manifest.run_id,
        terminal_status=canonical_terminal,
        blocked_reason=blocked,
        total_runtime_seconds=time.time() - start,
    )
    store.write_result(summary)
    store.update_manifest_status("blocked", canonical_terminal)
    return summary

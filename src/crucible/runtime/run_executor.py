"""Phase 8+: closed-loop runtime executor.

The v5.3 executor honestly ran verification commands, but it was still
single-pass and only emitted placeholder repair/review events. v5.4 keeps
that honesty while moving the deterministic task-closure loop into the real
runtime path.
"""

from __future__ import annotations

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
from crucible.failures.evidence_packet import FailureClass, FailureEvidencePacket
from crucible.failures.next_action_selector import NextAction, NextActionSelector
from crucible.orchestrator.closed_loop_executor import ClosedLoopExecutor, TaskContext, TaskStatus
from crucible.orchestrator.run_closure import RunClosure
from crucible.policy.budget_tracker import BudgetTracker
from crucible.policy.circuit_breaker import CircuitBreaker
from crucible.runner.non_identical_rule import NonIdenticalRetryRule
from crucible.runtime.run_store import (
    CostSummary,
    RunManifest,
    RunStore,
    RunSummary,
    TaskAttemptRecord,
)
from crucible.state.attempt_type import AttemptType
from crucible.state.workspace_record import WorkspaceLineageType, WorkspaceRecord
from crucible.workspace.manager import WorkspaceManager


AdapterFactory = Callable[[RunStore], list[BackendAdapter]]


TERMINAL_STATUSES = {
    TaskStatus.COMPLETE,
    TaskStatus.BLOCKED,
    TaskStatus.AWAITING_USER,
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

    store.append_event("orchestrator_started", payload={"workspace_root": workspace_root, "run_mode": "closed_loop"})
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

    tasks = plan.get("tasks", [])
    store.append_event("tasks_loaded", payload={"task_count": len(tasks)})

    completed: list[str] = []
    failed: list[str] = []
    partial: list[str] = []
    blockers: list[str] = []

    existing_winners = {
        a.task_id for a in store.list_attempts()
        if a.winning_attempt and a.status == AdapterStatus.COMPLETE.value
    }

    executor = ClosedLoopExecutor()

    for task in tasks:
        task_id = task["task_id"]
        if task_id in existing_winners:
            store.append_event("task_skipped_already_complete", task_id=task_id, payload={})
            completed.append(task_id)
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
        )

        if task_terminal == "complete":
            completed.append(task_id)
        elif task_terminal == "partial":
            partial.append(task_id)
            failed.append(task_id)
        else:
            failed.append(task_id)
        blockers.extend(task_blockers)

    task_states = ([{"task_id": task_id, "status": "complete"} for task_id in completed]
        + [{"task_id": task_id, "status": "blocked"} for task_id in failed]
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
    store.append_event("run_terminal", payload={"terminal_status": terminal})
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
        store.append_event("task_blocked", task_id=task_id, payload={"reason": "no criteria", "semantic_state": "blocked"})
        return "failed", ["no criteria"]

    task_blockers: list[str] = []
    ctx = executor.initialize_task(ctx)

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
                    store.append_event("task_completed", task_id=task_id, payload={"semantic_state": "complete", "winning_attempt_id": review_decision["accepted_attempt_id"]})
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
                store.append_event("task_completed", task_id=task_id, payload={"semantic_state": "complete", "winning_attempt_id": attempt.attempt_id})
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
                "semantic_state": "awaiting_user",
                "question_packet": decision.question_packet,
            })
            store.append_event("task_blocked", task_id=task_id, attempt_id=attempt.attempt_id, payload={
                "reason": failure_packet.human_summary,
                "semantic_state": "awaiting_user",
                "question_packet": decision.question_packet,
            })
            return ctx

        if decision.action == NextAction.BLOCKED:
            ctx.status = TaskStatus.BLOCKED
            store.append_event("task_failed", task_id=task_id, attempt_id=attempt.attempt_id, payload={
                "reason": failure_packet.human_summary,
                "semantic_state": "blocked",
            })
            store.append_event("task_blocked", task_id=task_id, attempt_id=attempt.attempt_id, payload={
                "reason": failure_packet.human_summary,
                "semantic_state": "blocked",
            })
            return ctx

        if decision.action == NextAction.REPAIR:
            store.append_event("repair_scheduled", task_id=task_id, attempt_id=attempt.attempt_id, payload={"attempt_type": "repair"})
            return executor._start_repair(ctx)
        if decision.action == NextAction.DEBUG:
            store.append_event("debug_scheduled", task_id=task_id, attempt_id=attempt.attempt_id, payload={"attempt_type": "debug"})
            return executor._start_debug(ctx)
        if decision.action == NextAction.SALVAGE:
            store.append_event("salvage_scheduled", task_id=task_id, attempt_id=attempt.attempt_id, payload={"attempt_type": "salvage"})
            return executor._start_salvage(ctx)
        if decision.action == NextAction.ENVIRONMENT_FIX:
            store.append_event("environment_fix_scheduled", task_id=task_id, attempt_id=attempt.attempt_id, payload={"attempt_type": "build", "budget_consumed": False})
            ctx.status = TaskStatus.QUEUED
            ctx.current_attempt = None
            return ctx

        ctx.status = TaskStatus.BLOCKED
        store.append_event("task_failed", task_id=task_id, attempt_id=attempt.attempt_id, payload={"reason": f"unsupported next action {decision.action.value}", "semantic_state": "blocked"})
        store.append_event("task_blocked", task_id=task_id, attempt_id=attempt.attempt_id, payload={"reason": f"unsupported next action {decision.action.value}", "semantic_state": "blocked"})
        task_blockers = [f"unsupported next action {decision.action.value}"]
        return ctx

    ctx = executor.execute_task(ctx, attempt_runner=_attempt_runner)
    if ctx.status == TaskStatus.COMPLETE:
        return "complete", []
    if ctx.status in {TaskStatus.BUILDING, TaskStatus.REPAIRING, TaskStatus.DEBUGGING, TaskStatus.SALVAGING, TaskStatus.INTEGRATING}:
        return "partial", task_blockers or [ctx.status.value]
    return "failed", task_blockers or [ctx.status.value]


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
    elif previous is not None and previous.workspace_record.path:
        _copy_workspace(Path(previous.workspace_record.path), target_path, exclude_roots=exclude_roots)
    return record


def _copy_workspace(src: Path, dest: Path, *, exclude_roots: list[Path] | None = None) -> None:
    if not src.exists():
        return
    exclude_roots = [p.resolve() for p in (exclude_roots or [])]
    for child in src.iterdir():
        resolved = child.resolve()
        if child.name in {"runs", ".git", "__pycache__"}:
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

        spec = AdapterRunSpec(
            spec_id=f"{task['task_id']}.{crit_id}",
            prompt=cmd,
            cwd=workspace_record.path or os.getcwd(),
            timeout_seconds=per_criterion_timeout_seconds,
            required_capabilities={Capability.SHELL_EXEC},
            metadata={
                "expected_output": expected,
                "build_target": build_target,
                "task_id": task["task_id"],
                "criterion_id": crit_id,
                "attempt_type": attempt_type.value,
                "attempt_id": attempt_id,
                "workspace_path": workspace_record.path,
                "workspace_mode": workspace_record.lineage_type.value,
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

        per_criterion_results.append({
            "criterion_id": crit_id,
            "criterion_class": crit_class,
            "verdict": verdict,
            "adapter_status": status.value,
            "summary": summary,
            "error": error,
            "build_target_checked": target_checked,
            "build_target_exists": target_exists,
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
            "review_required": task.get("review_required", False),
        },
    )
    store.write_attempt(attempt_record)
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
    review_spec = AdapterRunSpec(
        spec_id=f"{task['task_id']}.review",
        prompt=f"Review attempt {candidate_attempt_id} for task {task['task_id']}",
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
        },
    )
    store.write_attempt(attempt_record)
    return {
        "attempt_record": attempt_record,
        "criteria_results": [{"review_contract_valid": review_contract_ok, "candidate_attempt_id": candidate_attempt_id}],
        "failure_packet": None,
    }



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
        failure_class=FailureClass.VALIDATION_FAILURE,
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
        failure_class=FailureClass.VALIDATION_FAILURE,
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
        and a.failure_evidence.signature == provisional.signature
    ]
    if isinstance(structured, dict) and structured.get("failure_class") in {c.value for c in FailureClass}:
        failure_class = FailureClass(structured["failure_class"])
        root_cause = structured.get("root_cause_hypothesis")
        human_summary = structured.get("human_summary", "")
        machine_action = structured.get("machine_action", failure_class.value)
    elif build_target_exists is False:
        failure_class = FailureClass.VALIDATION_FAILURE
        root_cause = "missing_build_target"
        human_summary = f"validation_failure; criterion={criterion_id}; build_target missing"
        machine_action = failure_class.value
    elif adapter_status in {AdapterStatus.TIMED_OUT, AdapterStatus.KILLED}:
        failure_class = FailureClass.ENVIRONMENT_BLOCK
        root_cause = "executor_interrupted"
        human_summary = f"environment_block; criterion={criterion_id}; adapter_status={adapter_status.value}"
        machine_action = failure_class.value
    elif repeated:
        failure_class = FailureClass.LOOP_DETECTED
        root_cause = "repeated_failure_signature"
        human_summary = f"loop_detected; criterion={criterion_id}; repeated failing command"
        machine_action = failure_class.value
    else:
        failure_class = FailureClass.VALIDATION_FAILURE
        root_cause = "criteria_not_satisfied"
        human_summary = f"validation_failure; criterion={criterion_id}"
        machine_action = failure_class.value
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
        metadata={"adapter_status": adapter_status.value, "structured_failure": structured or {}},
    )


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

import json
from pathlib import Path

from crucible.accelerators.adapters import (
    AdapterRunHandle,
    AdapterRunResult,
    AdapterRunSpec,
    AdapterStatus,
    BackendAdapter,
)
from crucible.runtime.execution_models import evaluate_retry_admission
from crucible.accelerators.capabilities import BackendCapabilities, Capability
from crucible.runtime.preflight import lint_plan
from crucible.runtime.run_executor import execute_run
from crucible.runtime.run_store import create_run_store
from crucible.runtime.statuses import RunTerminalStatus


class BugfixAdapter(BackendAdapter):
    def __init__(self, *, first_build_passes: bool = False):
        self._caps = BackendCapabilities(
            backend_id="bugfix-adapter",
            supports={Capability.SHELL_EXEC, Capability.FILE_WRITE},
            max_concurrent_runs=1,
        )
        self._runs = {}
        self.spawned_specs = []
        self.first_build_passes = first_build_passes

    def backend_id(self) -> str:
        return "bugfix-adapter"

    def declared_capabilities(self) -> BackendCapabilities:
        return self._caps

    def spawn(self, spec: AdapterRunSpec) -> AdapterRunHandle:
        self.spawned_specs.append(spec)
        workspace = Path(spec.cwd)
        attempt_type = spec.metadata["attempt_type"]
        handle = AdapterRunHandle(handle_id=f"h-{spec.spec_id}", backend_id=self.backend_id(), spawned_at=0.0, spec_id=spec.spec_id)
        artifact = workspace / "src" / "bugfix.txt"
        artifact.parent.mkdir(parents=True, exist_ok=True)
        if attempt_type == "build":
            if self.first_build_passes:
                artifact.write_text("already green\n")
                result = AdapterRunResult(handle_id=handle.handle_id, status=AdapterStatus.COMPLETE, summary="build passed", artifact_paths=[str(artifact)])
            else:
                artifact.write_text("still broken\n")
                result = AdapterRunResult(handle_id=handle.handle_id, status=AdapterStatus.FAILED, error="repro captured", summary="build failed", artifact_paths=[str(artifact)])
        elif attempt_type == "repair":
            artifact.write_text("fixed\n")
            result = AdapterRunResult(handle_id=handle.handle_id, status=AdapterStatus.COMPLETE, summary="repair passed", artifact_paths=[str(artifact)])
        elif attempt_type == "review":
            review = workspace / "crucible_review.json"
            review.write_text(json.dumps({
                "verdict": "accept",
                "criterion_coverage": {"c1": True},
                "evidence_sufficient": True,
                "unresolved_risks": [],
            }))
            result = AdapterRunResult(handle_id=handle.handle_id, status=AdapterStatus.COMPLETE, summary="review accepted", artifact_paths=[str(review)])
        else:
            result = AdapterRunResult(handle_id=handle.handle_id, status=AdapterStatus.COMPLETE, summary=f"{attempt_type} noop", artifact_paths=[str(artifact)])
        self._runs[handle.handle_id] = result
        return handle

    def poll(self, handle: AdapterRunHandle) -> AdapterStatus:
        return self._runs[handle.handle_id].status

    def collect(self, handle: AdapterRunHandle) -> AdapterRunResult:
        return self._runs[handle.handle_id]

    def kill(self, handle: AdapterRunHandle) -> None:
        return None


def _bugfix_plan() -> dict:
    plan = {
        "spec": "bugfix protocol",
        "project_id": "phase3",
        "build_id": "b1",
        "tasks": [{
            "task_id": "task-1",
            "description": "Fix src/bugfix.txt regression with deterministic evidence",
            "criteria": [{
                "criterion_id": "c1",
                "criterion_class": "must_pass",
                "triple": {
                    "build_target": "src/bugfix.txt",
                    "verification_command": "echo PASS",
                    "expected_output": "PASS",
                },
            }],
            "role": "bugfix",
            "task_type": "bugfix",
            "review_required": True,
        }],
    }
    return lint_plan(plan).normalized_plan or plan


def test_phase3_persists_failed_strategy_and_threads_guardrails_into_retry(tmp_path):
    plan = _bugfix_plan()
    store, manifest = create_run_store(
        run_id=None,
        project_id=plan["project_id"],
        build_id=plan["build_id"],
        spec_text=plan.get("spec", ""),
        task_plan=plan,
        runs_root=str(tmp_path / "runs"),
        workspace_root=str(tmp_path / "seed"),
    )
    (tmp_path / "seed" / "src").mkdir(parents=True)
    adapter = BugfixAdapter()

    summary = execute_run(store=store, manifest=manifest, plan=plan, adapter_factory=lambda s: [adapter], workspace_root=str(tmp_path / "seed"))

    assert summary.terminal_status == RunTerminalStatus.SUCCEEDED.value
    repair_spec = next(spec for spec in adapter.spawned_specs if spec.metadata["attempt_type"] == "repair")
    packet = repair_spec.metadata["execution_packet"]
    assert packet["history"]["retry_guardrails"]["must_materially_differ"] is True
    assert packet["history"]["strategy_memory"]["entries"]
    assert "materially different strategy" in repair_spec.prompt

    strategy_path = Path(store.run_root) / packet["history"]["strategy_memory_ref"]
    strategy = json.loads(strategy_path.read_text())
    assert strategy["entries"][0]["do_not_repeat_without_change"] is True
    assert strategy["current_bugfix_state"] == "verified"


def test_phase3_bugfix_flow_persists_reproduce_fix_verify_state(tmp_path):
    plan = _bugfix_plan()
    store, manifest = create_run_store(
        run_id=None,
        project_id=plan["project_id"],
        build_id=plan["build_id"],
        spec_text=plan.get("spec", ""),
        task_plan=plan,
        runs_root=str(tmp_path / "runs"),
        workspace_root=str(tmp_path / "seed"),
    )
    (tmp_path / "seed" / "src").mkdir(parents=True)

    summary = execute_run(store=store, manifest=manifest, plan=plan, adapter_factory=lambda s: [BugfixAdapter()], workspace_root=str(tmp_path / "seed"))

    assert summary.terminal_status == RunTerminalStatus.SUCCEEDED.value
    attempts = store.attempts_for_task("task-1")
    assert attempts[0].metadata["structured_execution_result"]["current_bugfix_state"] == "reproduced"
    assert attempts[1].metadata["structured_execution_result"]["current_bugfix_state"] == "verified"
    assert attempts[2].metadata["structured_execution_result"]["current_bugfix_state"] == "verified"

    strategy_path = Path(store.run_root) / attempts[1].metadata["execution_packet"]["history"]["strategy_memory_ref"]
    strategy = json.loads(strategy_path.read_text())
    assert strategy["reproduction"]["status"] == "captured"
    assert strategy["reproduction"]["evidence_refs"]


def test_phase3_bugfix_requires_reproduction_evidence_before_success(tmp_path):
    plan = _bugfix_plan()
    store, manifest = create_run_store(
        run_id=None,
        project_id=plan["project_id"],
        build_id=plan["build_id"],
        spec_text=plan.get("spec", ""),
        task_plan=plan,
        runs_root=str(tmp_path / "runs"),
        workspace_root=str(tmp_path / "seed"),
    )
    (tmp_path / "seed" / "src").mkdir(parents=True)

    summary = execute_run(store=store, manifest=manifest, plan=plan, adapter_factory=lambda s: [BugfixAdapter(first_build_passes=True)], workspace_root=str(tmp_path / "seed"))

    assert summary.terminal_status == RunTerminalStatus.FAILED.value
    attempt = store.attempts_for_task("task-1")[0]
    assert attempt.status == "failed"
    assert attempt.failure_packet_ref
    assert attempt.metadata["structured_execution_result"]["current_bugfix_state"] == "investigating"
    assert "reproduction evidence" in attempt.blockers[0]


class ReproductionNotPossibleAdapter(BugfixAdapter):
    def spawn(self, spec: AdapterRunSpec) -> AdapterRunHandle:
        self.spawned_specs.append(spec)
        workspace = Path(spec.cwd)
        attempt_type = spec.metadata["attempt_type"]
        handle = AdapterRunHandle(handle_id=f"h-{spec.spec_id}", backend_id=self.backend_id(), spawned_at=0.0, spec_id=spec.spec_id)
        artifact = workspace / "src" / "bugfix.txt"
        artifact.parent.mkdir(parents=True, exist_ok=True)
        if attempt_type == "build":
            protocol = workspace / "crucible_bugfix.json"
            protocol.write_text(json.dumps({
                "state": "reproduction_not_possible",
                "why": "bug already disappeared on current head",
                "approaches_tried": ["reran failing command", "searched for historical failing test"],
                "surrogate_evidence": ["production stack trace attached", "code path identified"],
                "post_fix_validation": ["echo PASS"],
            }))
            artifact.write_text("fixed with surrogate validation\n")
            result = AdapterRunResult(handle_id=handle.handle_id, status=AdapterStatus.COMPLETE, summary="surrogate validation passed", artifact_paths=[str(artifact), str(protocol)])
        elif attempt_type == "review":
            return super().spawn(spec)
        else:
            artifact.write_text("noop\n")
            result = AdapterRunResult(handle_id=handle.handle_id, status=AdapterStatus.COMPLETE, summary=f"{attempt_type} noop", artifact_paths=[str(artifact)])
        self._runs[handle.handle_id] = result
        return handle


def test_phase3_retry_admission_requires_structural_delta_not_just_prompt_hint():
    strategy_memory = {
        "entries": [{
            "attempt_id": "attempt-001",
            "attempt_type": "repair",
            "do_not_repeat_without_change": True,
            "required_delta_for_retry": "preserve cookie path semantics",
            "evidence_refs": ["artifacts/task-1/validator-a1.json", "artifacts/task-1/failure-a1.json"],
        }],
    }

    blocked = evaluate_retry_admission(
        attempt_series=2,
        prior_evidence_refs=["artifacts/task-1/validator-a1.json", "artifacts/task-1/failure-a1.json"],
        strategy_memory=strategy_memory,
    )
    assert blocked["admitted"] is False
    assert blocked["reason"] == "required_delta_for_retry_not_structurally_satisfied"

    admitted = evaluate_retry_admission(
        attempt_series=2,
        prior_evidence_refs=[
            "artifacts/task-1/validator-a1.json",
            "artifacts/task-1/failure-a1.json",
            "artifacts/task-1/review-a2.json",
        ],
        strategy_memory=strategy_memory,
    )
    assert admitted["admitted"] is True
    assert admitted["reason"] == "new_durable_evidence_since_rejection"
    assert admitted["new_evidence_refs"] == ["artifacts/task-1/review-a2.json"]



def test_phase3_bugfix_allows_justified_reproduction_not_possible_with_durable_record(tmp_path):
    plan = _bugfix_plan()
    store, manifest = create_run_store(
        run_id=None,
        project_id=plan["project_id"],
        build_id=plan["build_id"],
        spec_text=plan.get("spec", ""),
        task_plan=plan,
        runs_root=str(tmp_path / "runs"),
        workspace_root=str(tmp_path / "seed"),
    )
    (tmp_path / "seed" / "src").mkdir(parents=True)

    summary = execute_run(store=store, manifest=manifest, plan=plan, adapter_factory=lambda s: [ReproductionNotPossibleAdapter(first_build_passes=True)], workspace_root=str(tmp_path / "seed"))

    assert summary.terminal_status == RunTerminalStatus.SUCCEEDED.value
    attempts = store.attempts_for_task("task-1")
    build_attempt = attempts[0]
    assert build_attempt.metadata["structured_execution_result"]["current_bugfix_state"] == "reproduction_not_possible"
    record_ref = build_attempt.metadata["bugfix_protocol_ref"]
    assert record_ref
    payload = json.loads((Path(store.run_root) / record_ref).read_text())
    assert payload["state"] == "reproduction_not_possible"
    strategy = json.loads((Path(store.run_root) / build_attempt.metadata["execution_packet"]["history"]["strategy_memory_ref"]).read_text())
    assert strategy["reproduction"]["status"] == "reproduction_not_possible"
    assert strategy["reproduction"]["reproduction_not_possible"]["post_fix_validation"] == ["echo PASS"]

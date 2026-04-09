import json
from pathlib import Path

from crucible.failures.evidence_packet import FailureClass

from crucible.accelerators.adapters import (
    AdapterRunHandle,
    AdapterRunResult,
    AdapterRunSpec,
    AdapterStatus,
    BackendAdapter,
)
from crucible.accelerators.capabilities import BackendCapabilities, Capability
from crucible.runtime.preflight import lint_plan
from crucible.runtime.run_executor import execute_run
from crucible.runtime.run_store import create_run_store


class RepairingAdapter(BackendAdapter):
    def __init__(self):
        self._caps = BackendCapabilities(
            backend_id="repairing-adapter",
            supports={Capability.SHELL_EXEC, Capability.FILE_WRITE},
            max_concurrent_runs=1,
        )
        self._runs = {}

    def backend_id(self) -> str:
        return "repairing-adapter"

    def declared_capabilities(self) -> BackendCapabilities:
        return self._caps

    def spawn(self, spec: AdapterRunSpec) -> AdapterRunHandle:
        workspace = Path(spec.cwd)
        target = workspace / "src" / "app.txt"
        target.parent.mkdir(parents=True, exist_ok=True)
        attempt_type = spec.metadata["attempt_type"]
        artifacts = [str(target)]
        if attempt_type == "build":
            target.write_text("broken\n")
            status = AdapterStatus.FAILED
            error = "criterion output mismatch"
            summary = "initial build failed"
        elif attempt_type == "repair":
            target.write_text("fixed\n")
            status = AdapterStatus.COMPLETE
            error = ""
            summary = "repair succeeded"
        elif attempt_type == "review":
            review = workspace / "crucible_review.json"
            review.write_text(json.dumps({
                "verdict": "accept",
                "criterion_coverage": {"c1": True},
                "evidence_sufficient": True,
                "unresolved_risks": [],
            }))
            status = AdapterStatus.COMPLETE
            error = ""
            summary = "review accepted"
            artifacts.append(str(review))
        else:
            status = AdapterStatus.COMPLETE
            error = ""
            summary = f"{attempt_type} noop"
        handle = AdapterRunHandle(handle_id=f"h-{spec.spec_id}", backend_id=self.backend_id(), spawned_at=0.0, spec_id=spec.spec_id)
        self._runs[handle.handle_id] = (status, error, summary, artifacts)
        return handle

    def poll(self, handle: AdapterRunHandle) -> AdapterStatus:
        return self._runs[handle.handle_id][0]

    def collect(self, handle: AdapterRunHandle) -> AdapterRunResult:
        status, error, summary, artifacts = self._runs[handle.handle_id]
        return AdapterRunResult(handle_id=handle.handle_id, status=status, error=error, summary=summary, artifact_paths=artifacts)

    def kill(self, handle: AdapterRunHandle) -> None:
        return None


def test_runtime_owns_build_fail_repair_retest_review_loop(tmp_path):
    plan = {
        "spec": "closed loop e2e",
        "project_id": "loop-e2e",
        "build_id": "b1",
        "tasks": [{
            "task_id": "task-1",
            "description": "prove the closed loop",
            "criteria": [{
                "criterion_id": "c1",
                "criterion_class": "must_pass",
                "triple": {
                    "build_target": "src/app.txt",
                    "verification_command": "echo PASS",
                    "expected_output": "PASS",
                },
            }],
            "role": "builder",
            "intensity_hint": "S",
            "review_required": True,
        }],
    }
    normalized = lint_plan(plan).normalized_plan or plan
    store, manifest = create_run_store(
        run_id=None,
        project_id=normalized["project_id"],
        build_id=normalized["build_id"],
        spec_text=normalized.get("spec", ""),
        task_plan=normalized,
        runs_root=str(tmp_path / "runs"),
        workspace_root=str(tmp_path / "seed"),
    )
    (tmp_path / "seed" / "src").mkdir(parents=True)

    summary = execute_run(
        store=store,
        manifest=manifest,
        plan=normalized,
        adapter_factory=lambda s: [RepairingAdapter()],
        workspace_root=str(tmp_path / "seed"),
    )

    assert summary.terminal_status == "complete"
    attempts = store.attempts_for_task("task-1")
    assert [a.attempt_type for a in attempts] == ["build", "repair", "review"]
    assert attempts[0].status == "failed"
    assert attempts[1].status == "complete"
    assert attempts[2].status == "complete"
    assert attempts[1].parent_attempt_id == attempts[0].attempt_id
    assert attempts[1].workspace_mode == "repair_basis"
    assert attempts[2].parent_attempt_id == attempts[1].attempt_id
    assert attempts[2].workspace_mode == "repair_basis"
    assert attempts[0].failure_packet_ref
    assert attempts[1].winning_attempt is True
    assert attempts[2].review_verdict == "accept"

    events = [json.loads(line) for line in Path(store.events_path).read_text().splitlines() if line.strip()]
    event_types = [e["type"] for e in events]
    assert "failure_packet_created" in event_types
    assert "next_action_selected" in event_types
    assert "repair_scheduled" in event_types
    assert "review_requested" in event_types
    assert "review_accepted" in event_types
    assert "task_completed" in event_types

    evidence_dir = Path(store.run_root) / "evidence" / "task-1"
    assert any(p.name.endswith("_evidence.json") for p in evidence_dir.iterdir())
    assert any(p.name.endswith("_manifest.json") for p in evidence_dir.iterdir())


class RejectingReviewerAdapter(RepairingAdapter):
    def spawn(self, spec: AdapterRunSpec) -> AdapterRunHandle:
        workspace = Path(spec.cwd)
        handle = AdapterRunHandle(handle_id=f"h-{spec.spec_id}", backend_id=self.backend_id(), spawned_at=0.0, spec_id=spec.spec_id)
        attempt_type = spec.metadata["attempt_type"]
        if attempt_type == "build":
            target = workspace / "src" / "app.txt"
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("fixed\n")
            self._runs[handle.handle_id] = (AdapterStatus.COMPLETE, "", "build succeeded", [str(target)])
            return handle
        if attempt_type == "review":
            review = workspace / "crucible_review.json"
            review.write_text(json.dumps({
                "verdict": "reject",
                "criterion_coverage": {"c1": True},
                "evidence_sufficient": False,
                "unresolved_risks": [],
            }))
            self._runs[handle.handle_id] = (AdapterStatus.COMPLETE, "", "review rejected", [str(review)])
            return handle
        return super().spawn(spec)


class EnvironmentFixAdapter(RepairingAdapter):
    def __init__(self):
        super().__init__()
        self._build_attempts = 0

    def spawn(self, spec: AdapterRunSpec) -> AdapterRunHandle:
        workspace = Path(spec.cwd)
        handle = AdapterRunHandle(handle_id=f"h-{spec.spec_id}", backend_id=self.backend_id(), spawned_at=0.0, spec_id=spec.spec_id)
        attempt_type = spec.metadata["attempt_type"]
        if attempt_type == "build":
            self._build_attempts += 1
            target = workspace / "src" / "app.txt"
            target.parent.mkdir(parents=True, exist_ok=True)
            if self._build_attempts == 1:
                target.write_text("stalled\n")
                self._runs[handle.handle_id] = (AdapterStatus.TIMED_OUT, "sandbox unavailable", "environment blocked", [str(target)])
            else:
                target.write_text("fixed\n")
                self._runs[handle.handle_id] = (AdapterStatus.COMPLETE, "", "environment recovered", [str(target)])
            return handle
        if attempt_type == "review":
            review = workspace / "crucible_review.json"
            review.write_text(json.dumps({
                "verdict": "accept",
                "criterion_coverage": {"c1": True},
                "evidence_sufficient": True,
                "unresolved_risks": [],
            }))
            self._runs[handle.handle_id] = (AdapterStatus.COMPLETE, "", "review accepted", [str(review)])
            return handle
        return super().spawn(spec)


class LenientAcceptReviewerAdapter(RepairingAdapter):
    def spawn(self, spec: AdapterRunSpec) -> AdapterRunHandle:
        workspace = Path(spec.cwd)
        handle = AdapterRunHandle(handle_id=f"h-{spec.spec_id}", backend_id=self.backend_id(), spawned_at=0.0, spec_id=spec.spec_id)
        attempt_type = spec.metadata["attempt_type"]
        if attempt_type == "build":
            target = workspace / "src" / "app.txt"
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("fixed\n")
            self._runs[handle.handle_id] = (AdapterStatus.COMPLETE, "", "build succeeded", [str(target)])
            return handle
        if attempt_type == "review":
            review = workspace / "crucible_review.json"
            review.write_text(json.dumps({
                "verdict": "accept",
                "criterion_coverage": {"c1": True},
                "evidence_sufficient": True,
                "unresolved_risks": ["watch for edge-case drift"],
                "escaped_defect_candidate": False,
            }))
            self._runs[handle.handle_id] = (AdapterStatus.COMPLETE, "", "review accepted", [str(review)])
            return handle
        return super().spawn(spec)



def test_environment_fix_continues_through_true_runtime_path(tmp_path):
    plan = {
        "spec": "environment fix continuation",
        "project_id": "loop-e2e",
        "build_id": "b-env",
        "tasks": [{
            "task_id": "task-1",
            "description": "prove environment fix resumes the real loop",
            "criteria": [{
                "criterion_id": "c1",
                "criterion_class": "must_pass",
                "triple": {
                    "build_target": "src/app.txt",
                    "verification_command": "echo PASS",
                    "expected_output": "PASS",
                },
            }],
            "role": "builder",
            "intensity_hint": "S",
            "review_required": True,
        }],
    }
    normalized = lint_plan(plan).normalized_plan or plan
    store, manifest = create_run_store(
        run_id=None,
        project_id=normalized["project_id"],
        build_id=normalized["build_id"],
        spec_text=normalized.get("spec", ""),
        task_plan=normalized,
        runs_root=str(tmp_path / "runs"),
        workspace_root=str(tmp_path / "seed"),
    )
    (tmp_path / "seed" / "src").mkdir(parents=True)

    summary = execute_run(
        store=store,
        manifest=manifest,
        plan=normalized,
        adapter_factory=lambda s: [EnvironmentFixAdapter()],
        workspace_root=str(tmp_path / "seed"),
    )

    assert summary.terminal_status == "complete"
    attempts = store.attempts_for_task("task-1")
    assert [a.attempt_type for a in attempts] == ["build", "repair", "review"]
    assert attempts[0].status == "failed"
    assert attempts[1].status == "complete"
    events = [json.loads(line) for line in Path(store.events_path).read_text().splitlines() if line.strip()]
    event_types = [e["type"] for e in events]
    assert "repair_scheduled" in event_types
    assert event_types.count("attempt_started") == 3
    assert "task_completed" in event_types


def test_review_accepts_valid_contract_with_extra_fields_and_non_blocking_risks(tmp_path):
    plan = {
        "spec": "lenient review acceptance",
        "project_id": "loop-e2e",
        "build_id": "b3",
        "tasks": [{
            "task_id": "task-1",
            "description": "prove reviewer accepts richer contract",
            "criteria": [{
                "criterion_id": "c1",
                "criterion_class": "must_pass",
                "triple": {
                    "build_target": "src/app.txt",
                    "verification_command": "echo PASS",
                    "expected_output": "PASS",
                },
            }],
            "role": "builder",
            "intensity_hint": "S",
            "review_required": True,
        }],
    }
    normalized = lint_plan(plan).normalized_plan or plan
    store, manifest = create_run_store(
        run_id=None,
        project_id=normalized["project_id"],
        build_id=normalized["build_id"],
        spec_text=normalized.get("spec", ""),
        task_plan=normalized,
        runs_root=str(tmp_path / "runs"),
        workspace_root=str(tmp_path / "seed"),
    )
    (tmp_path / "seed" / "src").mkdir(parents=True)

    summary = execute_run(
        store=store,
        manifest=manifest,
        plan=normalized,
        adapter_factory=lambda s: [LenientAcceptReviewerAdapter()],
        workspace_root=str(tmp_path / "seed"),
    )

    assert summary.terminal_status == "complete"
    attempts = store.attempts_for_task("task-1")
    assert attempts[-1].attempt_type == "review"
    assert attempts[-1].review_verdict == "accept"



class InvalidReviewContractAdapter(RepairingAdapter):
    def spawn(self, spec: AdapterRunSpec) -> AdapterRunHandle:
        workspace = Path(spec.cwd)
        handle = AdapterRunHandle(handle_id=f"h-{spec.spec_id}", backend_id=self.backend_id(), spawned_at=0.0, spec_id=spec.spec_id)
        attempt_type = spec.metadata["attempt_type"]
        if attempt_type == "build":
            target = workspace / "src" / "app.txt"
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("fixed\n")
            self._runs[handle.handle_id] = (AdapterStatus.COMPLETE, "", "build succeeded", [str(target)])
            return handle
        if attempt_type == "review":
            review = workspace / "crucible_review.json"
            review.write_text(json.dumps({"verdict": "accept"}))
            self._runs[handle.handle_id] = (AdapterStatus.COMPLETE, "", "malformed review", [str(review)])
            return handle
        return super().spawn(spec)



def test_invalid_review_contract_fails_closed_loop(tmp_path):
    plan = {
        "spec": "invalid review contract",
        "project_id": "loop-e2e",
        "build_id": "b4",
        "tasks": [{
            "task_id": "task-1",
            "description": "malformed review should not auto-pass",
            "criteria": [{
                "criterion_id": "c1",
                "criterion_class": "must_pass",
                "triple": {
                    "build_target": "src/app.txt",
                    "verification_command": "echo PASS",
                    "expected_output": "PASS",
                },
            }],
            "role": "builder",
            "intensity_hint": "S",
            "review_required": True,
        }],
    }
    normalized = lint_plan(plan).normalized_plan or plan
    store, manifest = create_run_store(
        run_id=None,
        project_id=normalized["project_id"],
        build_id=normalized["build_id"],
        spec_text=normalized.get("spec", ""),
        task_plan=normalized,
        runs_root=str(tmp_path / "runs"),
        workspace_root=str(tmp_path / "seed"),
    )
    (tmp_path / "seed" / "src").mkdir(parents=True)

    summary = execute_run(
        store=store,
        manifest=manifest,
        plan=normalized,
        adapter_factory=lambda s: [InvalidReviewContractAdapter()],
        workspace_root=str(tmp_path / "seed"),
    )

    assert summary.terminal_status == "failed"
    attempts = store.attempts_for_task("task-1")
    assert any(a.attempt_type == "review" and a.status == "failed" for a in attempts)
    events = [json.loads(line) for line in Path(store.events_path).read_text().splitlines() if line.strip()]
    event_types = [e["type"] for e in events]
    assert "task_completed" not in event_types



def test_run_closure_stays_open_when_integration_or_post_validation_required(tmp_path):
    plan = {
        "spec": "closure invariants",
        "project_id": "loop-e2e",
        "build_id": "b-closure",
        "integration_required": True,
        "post_integration_validation_required": True,
        "tasks": [{
            "task_id": "task-1",
            "description": "prove run closure does not over-close",
            "criteria": [{
                "criterion_id": "c1",
                "criterion_class": "must_pass",
                "triple": {
                    "build_target": "src/app.txt",
                    "verification_command": "echo PASS",
                    "expected_output": "PASS",
                },
            }],
            "role": "builder",
            "intensity_hint": "S",
            "review_required": False,
        }],
    }
    normalized = lint_plan(plan).normalized_plan or plan
    store, manifest = create_run_store(
        run_id=None,
        project_id=normalized["project_id"],
        build_id=normalized["build_id"],
        spec_text=normalized.get("spec", ""),
        task_plan=normalized,
        runs_root=str(tmp_path / "runs"),
        workspace_root=str(tmp_path / "seed"),
    )
    (tmp_path / "seed" / "src").mkdir(parents=True)

    summary = execute_run(
        store=store,
        manifest=manifest,
        plan=normalized,
        adapter_factory=lambda s: [LenientAcceptReviewerAdapter()],
        workspace_root=str(tmp_path / "seed"),
    )

    assert summary.terminal_status == "partial"
    assert summary.integration_status == "pending"
    assert "integration_incomplete" in summary.blocked_reason


def test_review_rejection_routes_to_debug_and_blocks_when_budget_exhausted(tmp_path):
    plan = {
        "spec": "review rejection path",
        "project_id": "loop-e2e",
        "build_id": "b2",
        "tasks": [{
            "task_id": "task-1",
            "description": "prove reviewer is real",
            "criteria": [{
                "criterion_id": "c1",
                "criterion_class": "must_pass",
                "triple": {
                    "build_target": "src/app.txt",
                    "verification_command": "echo PASS",
                    "expected_output": "PASS",
                },
            }],
            "role": "builder",
            "intensity_hint": "S",
            "review_required": True,
        }],
    }
    normalized = lint_plan(plan).normalized_plan or plan
    store, manifest = create_run_store(
        run_id=None,
        project_id=normalized["project_id"],
        build_id=normalized["build_id"],
        spec_text=normalized.get("spec", ""),
        task_plan=normalized,
        runs_root=str(tmp_path / "runs"),
        workspace_root=str(tmp_path / "seed"),
    )
    (tmp_path / "seed" / "src").mkdir(parents=True)

    summary = execute_run(
        store=store,
        manifest=manifest,
        plan=normalized,
        adapter_factory=lambda s: [RejectingReviewerAdapter()],
        workspace_root=str(tmp_path / "seed"),
    )

    assert summary.terminal_status == "failed"
    attempts = store.attempts_for_task("task-1")
    assert [a.attempt_type for a in attempts[:3]] == ["build", "review", "debug"]
    assert any(a.review_verdict == "reject" for a in attempts)
    events = [json.loads(line) for line in Path(store.events_path).read_text().splitlines() if line.strip()]
    event_types = [e["type"] for e in events]
    assert "review_rejected" in event_types
    assert "debug_scheduled" in event_types


def test_missing_env_toolchain_blocks_runtime_instead_of_crashing(tmp_path, monkeypatch):
    plan = {
        "spec": "runtime missing toolchain",
        "project_id": "loop-e2e",
        "build_id": "b-missing-toolchain",
        "tasks": [{
            "task_id": "task-1",
            "description": "prove missing uv becomes environment_block",
            "criteria": [{
                "criterion_id": "c1",
                "criterion_class": "must_pass",
                "triple": {
                    "build_target": "src/app.txt",
                    "verification_command": "echo PASS",
                    "expected_output": "PASS",
                },
            }],
            "role": "builder",
            "intensity_hint": "S",
            "review_required": False,
        }],
    }
    normalized = lint_plan(plan).normalized_plan or plan
    store, manifest = create_run_store(
        run_id=None,
        project_id=normalized["project_id"],
        build_id=normalized["build_id"],
        spec_text=normalized.get("spec", ""),
        task_plan=normalized,
        runs_root=str(tmp_path / "runs"),
        workspace_root=str(tmp_path / "seed"),
    )
    (tmp_path / "seed").mkdir(parents=True)
    (tmp_path / "seed" / "pyproject.toml").write_text(
        """
[project]
name = "demo"
version = "0.1.0"
""".strip()
    )
    monkeypatch.setenv("PATH", str(tmp_path / "missing-bin"))

    summary = execute_run(
        store=store,
        manifest=manifest,
        plan=normalized,
        adapter_factory=lambda s: [RepairingAdapter()],
        workspace_root=str(tmp_path / "seed"),
    )

    assert summary.terminal_status == "failed"
    attempts = store.attempts_for_task("task-1")
    assert attempts
    assert all(a.status == "failed" for a in attempts)
    assert all(a.metadata["environment"]["failure_class"] == "environment_block" for a in attempts)
    assert all(a.metadata["environment"]["missing_executables"] == ["uv"] for a in attempts)
    evidence = json.loads(Path(attempts[0].failure_packet_ref).read_text())
    assert evidence["failure_class"] == FailureClass.RETRYABLE.value
    assert "environment_hint" in evidence["hints"]
    assert evidence["error_message"] == "missing required executable: uv"
    events = [json.loads(line) for line in Path(store.events_path).read_text().splitlines() if line.strip()]
    assert any(event["type"] == "repair_scheduled" for event in events)

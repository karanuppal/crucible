import json
from pathlib import Path

from crucible.accelerators.adapters import (
    AdapterRunHandle,
    AdapterRunResult,
    AdapterRunSpec,
    AdapterStatus,
    BackendAdapter,
)
from crucible.accelerators.capabilities import BackendCapabilities, Capability
from crucible.runtime.execution_models import build_execution_packet, summarize_repo_context
from crucible.runtime.preflight import lint_plan
from crucible.runtime.run_executor import execute_run
from crucible.runtime.run_store import create_run_store


class PacketAwareAdapter(BackendAdapter):
    def __init__(self):
        self._caps = BackendCapabilities(
            backend_id="packet-aware",
            supports={Capability.SHELL_EXEC, Capability.FILE_WRITE},
            max_concurrent_runs=1,
        )
        self._runs = {}
        self.spawned_specs = []

    def backend_id(self) -> str:
        return "packet-aware"

    def declared_capabilities(self) -> BackendCapabilities:
        return self._caps

    def spawn(self, spec: AdapterRunSpec) -> AdapterRunHandle:
        self.spawned_specs.append(spec)
        workspace = Path(spec.cwd)
        attempt_type = spec.metadata["attempt_type"]
        handle = AdapterRunHandle(handle_id=f"h-{spec.spec_id}", backend_id=self.backend_id(), spawned_at=0.0, spec_id=spec.spec_id)
        if attempt_type == "review":
            review = workspace / "crucible_review.json"
            review.write_text(json.dumps({
                "verdict": "accept",
                "criterion_coverage": {"c1": True},
                "evidence_sufficient": True,
                "unresolved_risks": [],
            }))
            self._runs[handle.handle_id] = AdapterRunResult(handle_id=handle.handle_id, status=AdapterStatus.COMPLETE, artifact_paths=[str(review)], summary="review accepted")
        else:
            target = workspace / "src" / "module.py"
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("print('ok')\n")
            self._runs[handle.handle_id] = AdapterRunResult(handle_id=handle.handle_id, status=AdapterStatus.COMPLETE, artifact_paths=[str(target)], summary="build passed")
        return handle

    def poll(self, handle: AdapterRunHandle) -> AdapterStatus:
        return self._runs[handle.handle_id].status

    def collect(self, handle: AdapterRunHandle) -> AdapterRunResult:
        return self._runs[handle.handle_id]

    def kill(self, handle: AdapterRunHandle) -> None:
        return None


def test_repo_summary_prefers_build_targets(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "module.py").write_text("print('x')\n")
    task = {
        "task_id": "T1",
        "description": "Fix module behavior",
        "criteria": [{
            "criterion_id": "c1",
            "criterion_class": "must_pass",
            "triple": {
                "build_target": "src/module.py",
                "verification_command": "pytest -q",
            },
        }],
        "role": "builder",
    }
    summary = summarize_repo_context(str(tmp_path), task)
    assert summary["relevant_files"] == ["src/module.py"]


def test_execution_packet_contains_repo_context_policy_and_prior_evidence(tmp_path):
    task = {
        "task_id": "T1",
        "description": "Fix auth refresh regression",
        "criteria": [{
            "criterion_id": "c1",
            "criterion_class": "must_pass",
            "triple": {
                "build_target": "src/auth.py",
                "verification_command": "pytest tests/test_auth.py -q",
            },
        }],
        "role": "builder",
        "review_required": True,
    }
    packet = build_execution_packet(
        run_id="run-123",
        task=task,
        attempt_id="attempt-002",
        attempt_series=2,
        workspace_root=str(tmp_path),
        prior_attempts=[],
        prior_evidence_refs=["artifacts/failure-001.json"],
        strategy_memory_ref="artifacts/strategy-memory.json",
    )
    data = packet.to_dict()
    assert data["repo_context"]["workspace_path"] == str(tmp_path)
    assert data["repo_context"]["relevant_files"] == ["src/auth.py"]
    assert data["policy_snapshot"]["prompt_family"] == "builder-standard"
    assert data["validation_inputs"]["required_commands"] == ["pytest tests/test_auth.py -q"]
    assert data["history"]["prior_evidence_refs"] == ["artifacts/failure-001.json"]
    assert data["history"]["strategy_memory_ref"] == "artifacts/strategy-memory.json"


def test_execute_run_uses_task_aware_packet_in_default_path(tmp_path):
    plan = {
        "spec": "phase 2 packet path",
        "project_id": "phase2",
        "build_id": "b1",
        "tasks": [{
            "task_id": "task-1",
            "description": "Fix module behavior",
            "criteria": [{
                "criterion_id": "c1",
                "criterion_class": "must_pass",
                "triple": {
                    "build_target": "src/module.py",
                    "verification_command": "echo PASS",
                    "expected_output": "PASS",
                },
            }],
            "role": "builder",
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
    adapter = PacketAwareAdapter()

    summary = execute_run(
        store=store,
        manifest=manifest,
        plan=normalized,
        adapter_factory=lambda s: [adapter],
        workspace_root=str(tmp_path / "seed"),
    )

    assert summary.terminal_status == "run_succeeded"
    build_spec = next(spec for spec in adapter.spawned_specs if spec.metadata["attempt_type"] == "build")
    packet = build_spec.metadata["execution_packet"]
    assert packet["task_id"] == "task-1"
    assert packet["repo_context"]["relevant_files"] == ["src/module.py"]
    assert build_spec.metadata["command"] == "echo PASS"
    assert build_spec.prompt != "echo PASS"

    attempts = store.attempts_for_task("task-1")
    assert attempts[0].metadata["execution_packet"]["task_id"] == "task-1"
    assert attempts[0].metadata["structured_execution_result"]["status"] == "task_succeeded"


def test_execute_run_persists_repo_summary_and_strategy_memory_refs(tmp_path):
    plan = {
        "spec": "phase 2 packet artifacts",
        "project_id": "phase2",
        "build_id": "b1",
        "tasks": [{
            "task_id": "task-1",
            "description": "Fix module behavior",
            "criteria": [{
                "criterion_id": "c1",
                "criterion_class": "must_pass",
                "triple": {
                    "build_target": "src/module.py",
                    "verification_command": "echo PASS",
                    "expected_output": "PASS",
                },
            }],
            "role": "builder",
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
    adapter = PacketAwareAdapter()

    summary = execute_run(
        store=store,
        manifest=manifest,
        plan=normalized,
        adapter_factory=lambda s: [adapter],
        workspace_root=str(tmp_path / "seed"),
    )

    assert summary.terminal_status == "run_succeeded"
    build_attempt = store.attempts_for_task("task-1")[0]
    packet = build_attempt.metadata["execution_packet"]
    repo_summary_ref = packet["repo_context"]["repo_summary_ref"]
    strategy_memory_ref = packet["history"]["strategy_memory_ref"]

    repo_summary_path = Path(store.run_root) / repo_summary_ref
    strategy_memory_path = Path(store.run_root) / strategy_memory_ref

    assert repo_summary_path.exists()
    assert strategy_memory_path.exists()
    assert json.loads(repo_summary_path.read_text())["relevant_files"] == ["src/module.py"]
    strategy_memory = json.loads(strategy_memory_path.read_text())
    assert strategy_memory["phase"] == "phase-3"
    assert strategy_memory["current_bugfix_state"] == "investigating"


def test_execute_run_ignores_forged_in_memory_plan_and_uses_durable_plan_json(tmp_path):
    durable_plan = {
        "spec": "durable authority",
        "project_id": "phase2",
        "build_id": "b1",
        "tasks": [{
            "task_id": "task-1",
            "description": "Use persisted command",
            "criteria": [{
                "criterion_id": "c1",
                "criterion_class": "must_pass",
                "triple": {
                    "build_target": "src/module.py",
                    "verification_command": "echo PASS",
                    "expected_output": "PASS",
                },
            }],
            "role": "builder",
            "review_required": True,
        }],
    }
    forged_plan = json.loads(json.dumps(durable_plan))
    forged_plan["tasks"][0]["criteria"][0]["triple"]["verification_command"] = "echo FORGED"
    forged_plan["tasks"][0]["criteria"][0]["triple"]["build_target"] = "src/forged.py"
    forged_plan["tasks"][0]["description"] = "Forged runtime payload"

    normalized = lint_plan(durable_plan).normalized_plan or durable_plan
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
    adapter = PacketAwareAdapter()

    summary = execute_run(
        store=store,
        manifest=manifest,
        plan=forged_plan,
        adapter_factory=lambda s: [adapter],
        workspace_root=str(tmp_path / "seed"),
    )

    assert summary.terminal_status == "run_succeeded"
    build_spec = next(spec for spec in adapter.spawned_specs if spec.metadata["attempt_type"] == "build")
    assert build_spec.metadata["command"] == "echo PASS"
    assert build_spec.metadata["execution_packet"]["repo_context"]["relevant_files"] == ["src/module.py"]
    assert build_spec.metadata["execution_packet"]["task"]["goal"] == "Use persisted command"

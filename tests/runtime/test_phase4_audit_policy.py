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
from crucible.runtime.execution_models import build_execution_packet
from crucible.runtime.preflight import lint_plan
from crucible.runtime.run_executor import execute_run
from crucible.runtime.run_store import create_run_store


class Phase4Adapter(BackendAdapter):
    def __init__(self):
        self._caps = BackendCapabilities(
            backend_id="phase4-adapter",
            supports={Capability.SHELL_EXEC, Capability.FILE_WRITE},
            max_concurrent_runs=1,
        )
        self._runs = {}
        self.spawned_specs = []

    def backend_id(self) -> str:
        return "phase4-adapter"

    def declared_capabilities(self) -> BackendCapabilities:
        return self._caps

    def spawn(self, spec: AdapterRunSpec) -> AdapterRunHandle:
        self.spawned_specs.append(spec)
        workspace = Path(spec.cwd)
        handle = AdapterRunHandle(handle_id=f"h-{spec.spec_id}", backend_id=self.backend_id(), spawned_at=0.0, spec_id=spec.spec_id)
        attempt_type = spec.metadata["attempt_type"]
        if attempt_type == "review":
            review = workspace / "crucible_review.json"
            review.write_text(json.dumps({
                "verdict": "accept",
                "criterion_coverage": {"c1": True},
                "evidence_sufficient": True,
                "unresolved_risks": [],
            }))
            result = AdapterRunResult(handle_id=handle.handle_id, status=AdapterStatus.COMPLETE, artifact_paths=[str(review)], summary="review accepted")
        else:
            touched = workspace / "src" / "phase4.py"
            doc = workspace / "docs" / "phase4.md"
            touched.parent.mkdir(parents=True, exist_ok=True)
            doc.parent.mkdir(parents=True, exist_ok=True)
            touched.write_text("print('phase4')\n")
            doc.write_text("phase4 docs\n")
            result = AdapterRunResult(handle_id=handle.handle_id, status=AdapterStatus.COMPLETE, artifact_paths=[str(touched), str(doc)], summary="build passed")
        self._runs[handle.handle_id] = result
        return handle

    def poll(self, handle: AdapterRunHandle) -> AdapterStatus:
        return self._runs[handle.handle_id].status

    def collect(self, handle: AdapterRunHandle) -> AdapterRunResult:
        return self._runs[handle.handle_id]

    def kill(self, handle: AdapterRunHandle) -> None:
        return None


def _phase4_plan() -> dict:
    plan = {
        "spec": "phase 4 audit and policy persistence",
        "project_id": "phase4",
        "build_id": "b1",
        "tasks": [{
            "task_id": "task-1",
            "description": "Update src/phase4.py and verify audit artifacts exist",
            "criteria": [
                {
                    "criterion_id": "c1",
                    "criterion_class": "must_pass",
                    "triple": {
                        "build_target": "src/phase4.py",
                        "verification_command": "echo PASS_OK",
                        "expected_output": "PASS_OK",
                    },
                },
                {
                    "criterion_id": "info-1",
                    "criterion_class": "informational",
                    "triple": {
                        "build_target": "docs/phase4.md",
                        "verification_command": "echo INFO",
                        "expected_output": "INFO",
                    },
                },
            ],
            "role": "builder",
            "review_required": True,
            "review_policy": {"required": True, "tier": "strict"},
        }],
    }
    return lint_plan(plan).normalized_plan or plan


def test_phase4_execution_packet_preserves_explicit_review_policy(tmp_path):
    task = _phase4_plan()["tasks"][0]
    packet = build_execution_packet(
        run_id="run-123",
        task=task,
        attempt_id="attempt-001",
        attempt_series=1,
        workspace_root=str(tmp_path),
        prior_attempts=[],
        prior_evidence_refs=[],
    )

    assert packet.policy_snapshot["review_tier"] == "strict"
    assert packet.policy_snapshot["review_required"] is True
    assert packet.validation_inputs["must_pass"] == ["c1"]


def test_phase4_persists_prompt_audit_and_validator_chain_artifacts(tmp_path):
    plan = _phase4_plan()
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
    (tmp_path / "seed" / "docs").mkdir(parents=True)
    adapter = Phase4Adapter()

    summary = execute_run(store=store, manifest=manifest, plan=plan, adapter_factory=lambda s: [adapter], workspace_root=str(tmp_path / "seed"))

    assert summary.terminal_status in {"run_succeeded", "run_failed"}
    attempts = store.attempts_for_task("task-1")
    build_attempt = next(a for a in attempts if a.attempt_type == "build")
    review_attempt = next(a for a in attempts if a.attempt_type == "review")

    build_result = build_attempt.metadata["structured_execution_result"]
    validator_chain_path = Path(store.run_root) / build_result["artifact_refs"]["validator_chain"]
    prompt_audit_path = Path(store.run_root) / build_result["artifact_refs"]["prompt_audits"][0]
    review_prompt_audit_path = Path(store.run_root) / review_attempt.metadata["structured_execution_result"]["artifact_refs"]["prompt_audit"]

    assert validator_chain_path.exists()
    assert prompt_audit_path.exists()
    assert review_prompt_audit_path.exists()

    validator_chain = json.loads(validator_chain_path.read_text())
    prompt_audit = json.loads(prompt_audit_path.read_text())
    review_prompt_audit = json.loads(review_prompt_audit_path.read_text())

    assert validator_chain["review_policy"] == {"required": True, "tier": "strict"}
    assert validator_chain["validation_policy"]["must_pass"] == ["c1"]
    assert validator_chain["validation_policy"]["informational"] == ["info-1"]
    assert validator_chain["results"]["must_pass"][0]["criterion_id"] == "c1"
    assert validator_chain["results"]["informational"][0]["criterion_id"] == "info-1"
    assert prompt_audit["prompt_policy"]["family"] == "builder-standard"
    assert prompt_audit["prompt_instantiation"]["rendered_prompt"].startswith("Task:")
    assert prompt_audit["model_execution"]["provider"] == "phase4-adapter"
    assert review_prompt_audit["attempt_type"] == "review"

    assert build_attempt.metadata["review_policy"] == {"required": True, "tier": "strict"}
    assert build_attempt.metadata["validation_policy"]["informational"] == ["info-1"]
    assert review_attempt.metadata["review_policy"] == {"required": True, "tier": "strict"}

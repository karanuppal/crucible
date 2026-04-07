import json
from pathlib import Path

from crucible.accelerators.adapters import AdapterStatus
from crucible.failures.evidence_packet import FailureClass
from crucible.failures.next_action_selector import NextAction, NextActionSelector
from crucible.runtime.run_executor import _classify_failure
from crucible.state.attempt_type import AttemptType


def test_failure_classification_prefers_structured_failure_artifact(tmp_path):
    artifact = tmp_path / "crucible_failure.json"
    artifact.write_text(json.dumps({
        "failure_class": "missing_dependency",
        "root_cause_hypothesis": "api token absent",
        "human_summary": "missing dependency",
        "machine_action": "awaiting_user",
    }))

    packet = _classify_failure(
        attempt_id="task-1-attempt-1",
        task_id="task-1",
        criterion_id="c1",
        cmd="pytest",
        build_target="src/app.py",
        error="some opaque stderr",
        prior_attempts=[],
        attempt_type=AttemptType.BUILD,
        adapter_status=AdapterStatus.FAILED,
        artifact_paths=[str(artifact)],
        build_target_exists=True,
    )

    assert packet.failure_class == FailureClass.MISSING_DEPENDENCY
    assert packet.root_cause_hypothesis == "api token absent"
    assert packet.machine_action == "awaiting_user"


def test_failure_classification_uses_observed_state_not_error_substrings():
    packet = _classify_failure(
        attempt_id="task-1-attempt-1",
        task_id="task-1",
        criterion_id="c1",
        cmd="pytest",
        build_target="src/app.py",
        error="totally ambiguous wording with dependency mentioned",
        prior_attempts=[],
        attempt_type=AttemptType.BUILD,
        adapter_status=AdapterStatus.FAILED,
        artifact_paths=[],
        build_target_exists=False,
    )

    assert packet.failure_class == FailureClass.VALIDATION_FAILURE
    assert packet.root_cause_hypothesis == "missing_build_target"


def test_environment_block_routes_without_consuming_repair_budget():
    packet = _classify_failure(
        attempt_id="task-1-attempt-1",
        task_id="task-1",
        criterion_id="c1",
        cmd="pytest",
        build_target="src/app.py",
        error="killed by runtime",
        prior_attempts=[],
        attempt_type=AttemptType.BUILD,
        adapter_status=AdapterStatus.TIMED_OUT,
        artifact_paths=[],
        build_target_exists=True,
    )

    decision = NextActionSelector.select(packet, {"build_attempt_budget": 3, "repair_attempt_budget": 5})
    assert packet.failure_class == FailureClass.ENVIRONMENT_BLOCK
    assert decision.action == NextAction.ENVIRONMENT_FIX
    assert decision.budget_consumed is False



def test_failure_classification_detects_repeat_via_prior_signature_only():
    first = _classify_failure(
        attempt_id="task-1-attempt-1",
        task_id="task-1",
        criterion_id="c1",
        cmd="pytest",
        build_target="src/app.py",
        error="failed",
        prior_attempts=[],
        attempt_type=AttemptType.BUILD,
        adapter_status=AdapterStatus.FAILED,
        artifact_paths=[],
        build_target_exists=True,
    )

    prior = type('Attempt', (), {'failure_evidence': first, 'attempt_id': 'task-1-attempt-1'})()
    second = _classify_failure(
        attempt_id="task-1-attempt-2",
        task_id="task-1",
        criterion_id="c1",
        cmd="pytest",
        build_target="src/app.py",
        error="different text",
        prior_attempts=[prior],
        attempt_type=AttemptType.BUILD,
        adapter_status=AdapterStatus.FAILED,
        artifact_paths=[],
        build_target_exists=True,
    )

    assert second.failure_class == FailureClass.LOOP_DETECTED
    assert second.root_cause_hypothesis == "repeated_failure_signature"

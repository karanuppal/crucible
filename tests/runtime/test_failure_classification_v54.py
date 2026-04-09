import json

from crucible.accelerators.adapters import AdapterStatus
from crucible.failures.evidence_packet import FailureClass
from crucible.failures.next_action_selector import NextAction, NextActionSelector
from crucible.runtime.run_executor import _classify_failure
from crucible.state.attempt_type import AttemptType


def test_failure_classification_prefers_structured_failure_artifact(tmp_path):
    artifact = tmp_path / "crucible_failure.json"
    artifact.write_text(json.dumps({
        "failure_class": "needs_user_input",
        "root_cause_hypothesis": "api token absent",
        "human_summary": "missing credential",
        "machine_action": "awaiting_user",
        "hints": ["credential_hint"],
        "external_input_required": True,
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

    assert packet.failure_class == FailureClass.NEEDS_USER_INPUT
    assert packet.root_cause_hypothesis == "api token absent"
    assert packet.machine_action == "awaiting_user"
    assert packet.hints == ["credential_hint"]
    assert packet.external_input_required is True


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

    assert packet.failure_class == FailureClass.RETRYABLE
    assert packet.root_cause_hypothesis == "missing_build_target"
    assert "test_failure_hint" in packet.hints


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
    assert packet.failure_class == FailureClass.RETRYABLE
    assert decision.action == NextAction.REPAIR
    assert decision.budget_consumed is True


def test_failure_classification_detects_missing_dependency_from_error_shape():
    packet = _classify_failure(
        attempt_id="task-1-attempt-1",
        task_id="task-1",
        criterion_id="c1",
        cmd="pytest",
        build_target="src/app.py",
        error="ModuleNotFoundError: No module named 'requests'",
        prior_attempts=[],
        attempt_type=AttemptType.BUILD,
        adapter_status=AdapterStatus.FAILED,
        artifact_paths=[],
        build_target_exists=True,
    )

    assert packet.failure_class == FailureClass.RETRYABLE
    assert packet.root_cause_hypothesis == "dependency_or_project_package_missing"
    assert "dependency_hint" in packet.hints


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

    assert second.failure_class == FailureClass.STUCK_OR_REPEATING
    assert second.root_cause_hypothesis == "repeated_failure_signature"
    assert second.repeated_failure is True


def test_failure_classification_targets_missing_secret_not_approval():
    packet = _classify_failure(
        attempt_id="task-1-attempt-1",
        task_id="task-1",
        criterion_id="c1",
        cmd="pytest",
        build_target="src/app.py",
        error="Missing API key: OPENAI_API_KEY",
        prior_attempts=[],
        attempt_type=AttemptType.BUILD,
        adapter_status=AdapterStatus.FAILED,
        artifact_paths=[],
        build_target_exists=True,
    )

    decision = NextActionSelector.select(packet, {"repair_attempt_budget": 5})
    assert packet.failure_class == FailureClass.NEEDS_USER_INPUT
    assert packet.hints == ["credential_hint"]
    assert packet.metadata["required_user_input"]["target"] == "OPENAI_API_KEY"
    assert decision.question_packet["type"] == "credential_required"
    assert decision.question_packet["target"] == "OPENAI_API_KEY"


def test_failure_classification_targets_explicit_approval_when_present():
    packet = _classify_failure(
        attempt_id="task-1-attempt-1",
        task_id="task-1",
        criterion_id="c1",
        cmd="pytest",
        build_target="src/app.py",
        error="Approval required: install production dependency",
        prior_attempts=[],
        attempt_type=AttemptType.BUILD,
        adapter_status=AdapterStatus.FAILED,
        artifact_paths=[],
        build_target_exists=True,
    )

    decision = NextActionSelector.select(packet, {"repair_attempt_budget": 5})
    assert packet.metadata["required_user_input"]["target"] == "install production dependency"
    assert decision.question_packet["type"] == "approval_required"

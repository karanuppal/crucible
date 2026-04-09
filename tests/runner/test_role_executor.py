from crucible.failures.evidence_packet import FailureClass, FailureEvidencePacket
from crucible.runner.role_executor import RoleExecutor
from crucible.state.attempt_type import AttemptType


def test_recovery_prompt_includes_v61_required_sections():
    executor = RoleExecutor()
    failure = FailureEvidencePacket(
        failure_class=FailureClass.RETRYABLE,
        attempt_id="task-1-attempt-2",
        task_id="task-1",
        criterion="c1",
        error_message="AssertionError: expected PASS",
        human_summary="verification failed on c1",
        failing_command="pytest -q",
        evidence_refs=["logs/test.log"],
        hints=["test_failure_hint"],
    )

    prompt = executor.get_prompt_for_attempt(
        AttemptType.REPAIR,
        {
            "task_goal": "Make the test suite pass for task-1.",
            "current_failure": "Criterion c1 still fails after the last edit.",
            "raw_command_output": "AssertionError: expected PASS\nE assert 'FAIL' == 'PASS'",
            "failure_evidence": failure,
            "prior_attempts_summary": "Attempt 1 changed parsing logic but the same assertion still failed.",
        },
    )

    assert "Task goal:" in prompt
    assert "Current failure:" in prompt
    assert "Raw command output:" in prompt
    assert "Structured evidence packet:" in prompt
    assert "Prior attempts summary:" in prompt
    assert "explicitly verify it" in prompt
    assert "Do not claim success without verification." in prompt


def test_stuck_or_repeating_prompt_forces_materially_different_strategy_and_summary():
    executor = RoleExecutor()
    failure = FailureEvidencePacket(
        failure_class=FailureClass.STUCK_OR_REPEATING,
        attempt_id="task-1-attempt-3",
        task_id="task-1",
        criterion="c1",
        error_message="Same failing assertion after multiple fixes",
        human_summary="stuck_or_repeating on c1",
        failing_command="pytest tests/test_app.py -q",
        repeated_failure=True,
    )

    prompt = executor.get_prompt_for_attempt(
        AttemptType.DEBUG,
        {
            "task_goal": "Get tests/test_app.py green.",
            "failure_evidence": failure,
            "prior_attempts": [
                {"attempt_id": "a1", "status": "failed", "approach": "patched parser branch"},
                {"attempt_id": "a2", "status": "failed", "approach": "changed fixture setup only"},
            ],
        },
    )

    assert "stuck_or_repeating" in prompt
    assert "summarize the prior failed approaches" in prompt
    assert "materially different strategy" in prompt
    assert "- a1: failed; patched parser branch" in prompt
    assert "- a2: failed; changed fixture setup only" in prompt

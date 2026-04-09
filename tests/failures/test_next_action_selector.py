"""Tests for next action selector."""

from crucible.failures.evidence_packet import FailureClass, FailureEvidencePacket
from crucible.failures.next_action_selector import NextAction, NextActionSelector
from crucible.state.attempt_type import AttemptType


class TestNextActionSelector:
    def test_needs_user_input_awaits_user(self):
        evidence = FailureEvidencePacket(
            failure_class=FailureClass.NEEDS_USER_INPUT,
            attempt_id="attempt-1",
            hints=["ambiguity_hint"],
        )
        decision = NextActionSelector.select(evidence, {"repair_attempt_budget": 5})
        assert decision.action == NextAction.AWAITING_USER
        assert decision.requires_user_input is True
        assert decision.budget_consumed is False

    def test_retryable_environment_hint_launches_fix(self):
        evidence = FailureEvidencePacket(
            failure_class=FailureClass.RETRYABLE,
            attempt_id="attempt-2",
            hints=["environment_hint"],
        )
        decision = NextActionSelector.select(evidence, {"repair_attempt_budget": 3})
        assert decision.action == NextAction.REPAIR
        assert decision.attempt_type == AttemptType.REPAIR
        assert decision.budget_key == "repair_attempt_budget"

    def test_retryable_default_routes_to_repair(self):
        evidence = FailureEvidencePacket(
            failure_class=FailureClass.RETRYABLE,
            attempt_id="attempt-3",
            criterion="c1",
        )
        decision = NextActionSelector.select(evidence, {"repair_attempt_budget": 5})
        assert decision.action == NextAction.REPAIR
        assert decision.attempt_type == AttemptType.REPAIR

    def test_retryable_integration_hint_routes_to_integrate(self):
        evidence = FailureEvidencePacket(
            failure_class=FailureClass.RETRYABLE,
            attempt_id="attempt-4",
            hints=["integration_hint"],
        )
        decision = NextActionSelector.select(evidence, {"integration_attempt_budget": 3})
        assert decision.action == NextAction.INTEGRATE
        assert decision.attempt_type == AttemptType.INTEGRATE

    def test_stuck_or_repeating_routes_to_debug(self):
        evidence = FailureEvidencePacket(
            failure_class=FailureClass.STUCK_OR_REPEATING,
            attempt_id="attempt-5",
            repeated_failure=True,
            root_cause_hypothesis="same assertion after multiple shallow fixes",
        )
        decision = NextActionSelector.select(evidence, {"deep_recovery_budget": 2})
        assert decision.action == NextAction.DEBUG
        assert decision.attempt_type == AttemptType.DEBUG
        assert decision.budget_key == "deep_recovery_budget"

    def test_retryable_repeated_signature_escalates_to_deep_recovery(self):
        evidence = FailureEvidencePacket(
            failure_class=FailureClass.RETRYABLE,
            attempt_id="attempt-6",
            criterion="test_output_matches",
            repeated_failure=True,
        )
        decision = NextActionSelector.select(
            evidence,
            {"repair_attempt_budget": 5, "deep_recovery_budget": 2},
            attempt_history=[{"signature": evidence.signature}, {"signature": evidence.signature}],
        )
        assert decision.action == NextAction.DEBUG
        assert decision.attempt_type == AttemptType.DEBUG
        assert decision.rule_fired == "retryable:repeated_signature->deep_recovery"

    def test_terminal_nonrecoverable_blocks(self):
        evidence = FailureEvidencePacket(
            failure_class=FailureClass.TERMINAL_NONRECOVERABLE,
            attempt_id="attempt-7",
        )
        decision = NextActionSelector.select(evidence, {"repair_attempt_budget": 5})
        assert decision.action == NextAction.BLOCKED
        assert decision.budget_consumed is False

    def test_repair_budget_exhausted_blocks(self):
        evidence = FailureEvidencePacket(
            failure_class=FailureClass.RETRYABLE,
            attempt_id="attempt-8",
            criterion="test_criterion",
        )
        decision = NextActionSelector.select(evidence, {"repair_attempt_budget": 0})
        assert decision.action == NextAction.BLOCKED
        assert decision.budget_consumed is False

    def test_deep_recovery_budget_exhausted_blocks(self):
        evidence = FailureEvidencePacket(
            failure_class=FailureClass.STUCK_OR_REPEATING,
            attempt_id="attempt-9",
        )
        decision = NextActionSelector.select(evidence, {"deep_recovery_budget": 0})
        assert decision.action == NextAction.BLOCKED

    def test_deterministic_same_input(self):
        evidence = FailureEvidencePacket(
            failure_class=FailureClass.RETRYABLE,
            attempt_id="attempt-10",
            criterion="test_criterion",
        )
        result1 = NextActionSelector.select(evidence, {"repair_attempt_budget": 5})
        result2 = NextActionSelector.select(evidence, {"repair_attempt_budget": 5})
        assert result1.action == result2.action
        assert result1.attempt_type == result2.attempt_type
        assert result1.reasoning == result2.reasoning

    def test_question_packet_for_user_required(self):
        evidence = FailureEvidencePacket(
            failure_class=FailureClass.NEEDS_USER_INPUT,
            attempt_id="attempt-11",
            evidence_refs=["spec.md"],
            hints=["ambiguity_hint"],
        )
        decision = NextActionSelector.select(evidence, {"repair_attempt_budget": 5})
        assert decision.question_packet is not None
        assert decision.question_packet["type"] == "clarification_needed"

    def test_reasoning_and_inputs_include_audit_context(self):
        evidence = FailureEvidencePacket(
            failure_class=FailureClass.RETRYABLE,
            attempt_id="attempt-12",
            criterion="test_criterion",
            hints=["dependency_hint"],
        )
        decision = NextActionSelector.select(
            evidence,
            {"repair_attempt_budget": 5},
            rejection_ledger=[{"action": "repair"}],
            workspace_policy="fresh_per_attempt",
        )
        assert "retryable" in decision.reasoning.lower()
        assert decision.inputs_considered["workspace_policy"] == "fresh_per_attempt"

    def test_root_cause_in_reasoning(self):
        evidence = FailureEvidencePacket(
            failure_class=FailureClass.STUCK_OR_REPEATING,
            attempt_id="attempt-13",
            root_cause_hypothesis="infinite recursion in parse loop",
        )
        decision = NextActionSelector.select(evidence, {"deep_recovery_budget": 3})
        assert "infinite recursion" in decision.reasoning

    def test_matrix_covers_all_known_classes(self):
        assert set(FailureClass) == set(NextActionSelector._ACTION_MATRIX)


    def test_question_packet_uses_targeted_requirement_metadata(self):
        evidence = FailureEvidencePacket(
            failure_class=FailureClass.NEEDS_USER_INPUT,
            attempt_id="attempt-12b",
            metadata={"required_user_input": {"type": "credential_required", "target": "OPENAI_API_KEY", "source": "error_message"}},
        )
        decision = NextActionSelector.select(evidence, {"repair_attempt_budget": 5})
        assert decision.question_packet == {
            "type": "credential_required",
            "question": "Missing credential or secret required to proceed: OPENAI_API_KEY.",
            "evidence_refs": [],
            "task_id": None,
            "attempt_id": "attempt-12b",
            "target": "OPENAI_API_KEY",
            "source": "error_message",
        }

"""Tests for next action selector."""

from crucible.failures.evidence_packet import FailureClass, FailureEvidencePacket
from crucible.failures.next_action_selector import NextAction, NextActionSelector
from crucible.state.attempt_type import AttemptType


class TestNextActionSelector:
    def test_ambiguity_block_awaits_user(self):
        evidence = FailureEvidencePacket(
            failure_class=FailureClass.AMBIGUITY_BLOCK,
            attempt_id="attempt-1",
        )
        decision = NextActionSelector.select(evidence, {"repair_attempt_budget": 5})
        assert decision.action == NextAction.AWAITING_USER
        assert decision.requires_user_input is True
        assert decision.budget_consumed is False

    def test_environment_block_launches_fix(self):
        evidence = FailureEvidencePacket(
            failure_class=FailureClass.ENVIRONMENT_BLOCK,
            attempt_id="attempt-2",
        )
        decision = NextActionSelector.select(evidence, {"build_attempt_budget": 3})
        assert decision.action == NextAction.ENVIRONMENT_FIX
        assert decision.attempt_type == AttemptType.BUILD
        assert decision.budget_consumed is False

    def test_missing_dependency_awaits_user(self):
        evidence = FailureEvidencePacket(
            failure_class=FailureClass.MISSING_DEPENDENCY,
            attempt_id="attempt-3",
        )
        decision = NextActionSelector.select(evidence, {"repair_attempt_budget": 5})
        assert decision.action == NextAction.AWAITING_USER
        assert decision.requires_user_input is True

    def test_architecture_mismatch_blocks(self):
        evidence = FailureEvidencePacket(
            failure_class=FailureClass.ARCHITECTURE_MISMATCH,
            attempt_id="attempt-4",
        )
        decision = NextActionSelector.select(evidence, {"repair_attempt_budget": 5})
        assert decision.action == NextAction.BLOCKED
        assert decision.budget_consumed is True

    def test_model_limitation_repair(self):
        evidence = FailureEvidencePacket(
            failure_class=FailureClass.MODEL_LIMITATION,
            attempt_id="attempt-5",
        )
        decision = NextActionSelector.select(evidence, {"repair_attempt_budget": 5})
        assert decision.action == NextAction.REPAIR
        assert decision.attempt_type == AttemptType.REPAIR

    def test_validation_failure_repair(self):
        evidence = FailureEvidencePacket(
            failure_class=FailureClass.VALIDATION_FAILURE,
            attempt_id="attempt-6",
            criterion="test_output_matches",
        )
        decision = NextActionSelector.select(evidence, {"repair_attempt_budget": 5})
        assert decision.action == NextAction.REPAIR
        assert decision.attempt_type == AttemptType.REPAIR

    def test_validation_failure_repeated_signature_routes_to_debug(self):
        evidence = FailureEvidencePacket(
            failure_class=FailureClass.VALIDATION_FAILURE,
            attempt_id="attempt-6b",
            criterion="test_output_matches",
        )
        decision = NextActionSelector.select(
            evidence,
            {"repair_attempt_budget": 5, "debug_attempt_budget": 2},
            attempt_history=[{"signature": evidence.signature}, {"signature": evidence.signature}],
        )
        assert decision.action == NextAction.DEBUG
        assert decision.attempt_type == AttemptType.DEBUG
        assert decision.rule_fired == "validation_failure:repeated_signature->debug"

    def test_integration_conflict_integrate(self):
        evidence = FailureEvidencePacket(
            failure_class=FailureClass.INTEGRATION_CONFLICT,
            attempt_id="attempt-7",
        )
        decision = NextActionSelector.select(evidence, {"integration_budget": 3})
        assert decision.action == NextAction.INTEGRATE
        assert decision.attempt_type == AttemptType.INTEGRATE

    def test_loop_detected_debug(self):
        evidence = FailureEvidencePacket(
            failure_class=FailureClass.LOOP_DETECTED,
            attempt_id="attempt-8",
            root_cause_hypothesis="repeated assertion error",
        )
        decision = NextActionSelector.select(evidence, {"debug_attempt_budget": 2})
        assert decision.action == NextAction.DEBUG
        assert decision.attempt_type == AttemptType.DEBUG

    def test_repair_budget_exhausted_blocks(self):
        evidence = FailureEvidencePacket(
            failure_class=FailureClass.VALIDATION_FAILURE,
            attempt_id="attempt-9",
            criterion="test_criterion",
        )
        decision = NextActionSelector.select(evidence, {"repair_attempt_budget": 0})
        assert decision.action == NextAction.BLOCKED
        assert decision.budget_consumed is False

    def test_debug_budget_exhausted_blocks(self):
        evidence = FailureEvidencePacket(
            failure_class=FailureClass.LOOP_DETECTED,
            attempt_id="attempt-10",
        )
        decision = NextActionSelector.select(evidence, {"debug_attempt_budget": 0})
        assert decision.action == NextAction.BLOCKED

    def test_deterministic_same_input(self):
        evidence = FailureEvidencePacket(
            failure_class=FailureClass.VALIDATION_FAILURE,
            attempt_id="attempt-11",
            criterion="test_criterion",
        )
        result1 = NextActionSelector.select(evidence, {"repair_attempt_budget": 5})
        result2 = NextActionSelector.select(evidence, {"repair_attempt_budget": 5})
        assert result1.action == result2.action
        assert result1.attempt_type == result2.attempt_type
        assert result1.reasoning == result2.reasoning

    def test_question_packet_for_user_required(self):
        evidence = FailureEvidencePacket(
            failure_class=FailureClass.AMBIGUITY_BLOCK,
            attempt_id="attempt-14",
            evidence_refs=["spec.md"],
        )
        decision = NextActionSelector.select(evidence, {"repair_attempt_budget": 5})
        assert decision.question_packet is not None
        assert decision.question_packet["type"] == "clarification_needed"

    def test_reasoning_and_inputs_include_audit_context(self):
        evidence = FailureEvidencePacket(
            failure_class=FailureClass.VALIDATION_FAILURE,
            attempt_id="attempt-15",
            criterion="test_criterion",
        )
        decision = NextActionSelector.select(
            evidence,
            {"repair_attempt_budget": 5},
            rejection_ledger=[{"action": "repair"}],
            workspace_policy="fresh_per_attempt",
        )
        assert "validation_failure" in decision.reasoning.lower()
        assert decision.inputs_considered["workspace_policy"] == "fresh_per_attempt"

    def test_root_cause_in_reasoning(self):
        evidence = FailureEvidencePacket(
            failure_class=FailureClass.LOOP_DETECTED,
            attempt_id="attempt-16",
            root_cause_hypothesis="infinite recursion in parse loop",
        )
        decision = NextActionSelector.select(evidence, {"debug_attempt_budget": 3})
        assert "infinite recursion" in decision.reasoning

    def test_unknown_failure_class_matrix_covers_all_known_cases(self):
        assert set(FailureClass) == set(NextActionSelector._ACTION_MATRIX)

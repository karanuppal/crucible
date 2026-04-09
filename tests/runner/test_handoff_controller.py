"""Tests for the v6.1 handoff controller."""

from crucible.failures.evidence_packet import FailureClass, FailureEvidencePacket
from crucible.runner.handoff_controller import HandoffController, Role
from crucible.state.attempt_state import AttemptState
from crucible.state.attempt_type import AttemptType


class TestHandoffController:
    def test_validation_pass_routes_to_review(self):
        decision = HandoffController.decide_handoff(
            current_state=AttemptState.VALIDATED_PASS,
            attempt_type=AttemptType.BUILD,
        )
        assert decision.to_role == Role.REVIEWER
        assert decision.attempt_type == AttemptType.REVIEW

    def test_validation_pass_repair_also_routes_to_review(self):
        decision = HandoffController.decide_handoff(
            current_state=AttemptState.VALIDATED_PASS,
            attempt_type=AttemptType.REPAIR,
        )
        assert decision.to_role == Role.REVIEWER
        assert decision.attempt_type == AttemptType.REVIEW

    def test_retryable_failure_routes_to_repair(self):
        evidence = FailureEvidencePacket(
            failure_class=FailureClass.RETRYABLE,
            attempt_id="attempt-1",
            criterion="test_criterion",
        )
        decision = HandoffController.decide_handoff(
            current_state=AttemptState.VALIDATED_FAIL,
            attempt_type=AttemptType.BUILD,
            failure_evidence=evidence,
        )
        assert decision.attempt_type == AttemptType.REPAIR
        assert decision.requires_user_input is False
        assert decision.terminal is False

    def test_stuck_or_repeating_routes_to_debugger(self):
        evidence = FailureEvidencePacket(
            failure_class=FailureClass.STUCK_OR_REPEATING,
            attempt_id="attempt-2",
        )
        decision = HandoffController.decide_handoff(
            current_state=AttemptState.VALIDATED_FAIL,
            attempt_type=AttemptType.REPAIR,
            failure_evidence=evidence,
        )
        assert decision.to_role == Role.DEBUGGER
        assert decision.attempt_type == AttemptType.DEBUG

    def test_first_retryable_failure_routes_to_repair(self):
        evidence = FailureEvidencePacket(
            failure_class=FailureClass.RETRYABLE,
            attempt_id="attempt-3",
            criterion="test_criterion",
            root_cause_hypothesis=None,
        )
        decision = HandoffController.decide_handoff(
            current_state=AttemptState.VALIDATED_FAIL,
            attempt_type=AttemptType.BUILD,
            failure_evidence=evidence,
        )
        assert decision.attempt_type == AttemptType.REPAIR

    def test_repeated_retryable_failure_routes_to_debugger(self):
        evidence = FailureEvidencePacket(
            failure_class=FailureClass.RETRYABLE,
            attempt_id="attempt-4",
            criterion="test_criterion",
            prior_attempts=["attempt-1", "attempt-2"],
            repeated_failure=True,
        )
        decision = HandoffController.decide_handoff(
            current_state=AttemptState.VALIDATED_FAIL,
            attempt_type=AttemptType.REPAIR,
            failure_evidence=evidence,
        )
        assert decision.to_role == Role.DEBUGGER
        assert decision.attempt_type == AttemptType.DEBUG

    def test_review_accept_routes_to_complete(self):
        review_result = {"verdict": "accept"}
        decision = HandoffController.decide_handoff(
            current_state=AttemptState.VALIDATED_PASS,
            attempt_type=AttemptType.REVIEW,
            review_result=review_result,
        )
        assert decision.from_role == Role.REVIEWER

    def test_review_reject_routes_to_repair(self):
        review_result = {"verdict": "reject", "rejection_type": "general"}
        decision = HandoffController.decide_handoff(
            current_state=AttemptState.VALIDATED_PASS,
            attempt_type=AttemptType.REVIEW,
            review_result=review_result,
        )
        assert decision.attempt_type == AttemptType.REPAIR

    def test_review_reject_missing_explanation_routes_to_debugger(self):
        review_result = {"verdict": "reject", "rejection_type": "missing_causal_explanation"}
        decision = HandoffController.decide_handoff(
            current_state=AttemptState.VALIDATED_PASS,
            attempt_type=AttemptType.REVIEW,
            review_result=review_result,
        )
        assert decision.to_role == Role.DEBUGGER
        assert decision.attempt_type == AttemptType.DEBUG

    def test_partial_routes_to_salvage(self):
        decision = HandoffController.decide_handoff(
            current_state=AttemptState.PARTIAL,
            attempt_type=AttemptType.BUILD,
        )
        assert decision.to_role == Role.SALVAGE
        assert decision.attempt_type == AttemptType.SALVAGE

    def test_default_routes_to_builder(self):
        decision = HandoffController.decide_handoff(
            current_state=AttemptState.PENDING,
            attempt_type=AttemptType.BUILD,
        )
        assert decision.to_role == Role.BUILDER
        assert decision.attempt_type == AttemptType.BUILD

    def test_get_role_for_attempt_type(self):
        assert HandoffController.get_role_for_attempt_type(AttemptType.BUILD) == Role.BUILDER
        assert HandoffController.get_role_for_attempt_type(AttemptType.REPAIR) == Role.BUILDER
        assert HandoffController.get_role_for_attempt_type(AttemptType.DEBUG) == Role.DEBUGGER
        assert HandoffController.get_role_for_attempt_type(AttemptType.REVIEW) == Role.REVIEWER
        assert HandoffController.get_role_for_attempt_type(AttemptType.SALVAGE) == Role.SALVAGE
        assert HandoffController.get_role_for_attempt_type(AttemptType.INTEGRATE) == Role.INTEGRATOR

    def test_needs_user_input_pauses_without_selecting_next_attempt(self):
        evidence = FailureEvidencePacket(
            failure_class=FailureClass.NEEDS_USER_INPUT,
            attempt_id="attempt-5",
        )
        decision = HandoffController.decide_handoff(
            current_state=AttemptState.VALIDATED_FAIL,
            attempt_type=AttemptType.BUILD,
            failure_evidence=evidence,
        )
        assert decision.requires_user_input is True
        assert decision.terminal is False
        assert decision.attempt_type is None

    def test_terminal_nonrecoverable_stops_without_selecting_next_attempt(self):
        evidence = FailureEvidencePacket(
            failure_class=FailureClass.TERMINAL_NONRECOVERABLE,
            attempt_id="attempt-6",
        )
        decision = HandoffController.decide_handoff(
            current_state=AttemptState.VALIDATED_FAIL,
            attempt_type=AttemptType.BUILD,
            failure_evidence=evidence,
        )
        assert decision.requires_user_input is False
        assert decision.terminal is True
        assert decision.attempt_type is None

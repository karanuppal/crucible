"""
Tests for role handoff controller.

Phase 3: Role Handoff Controller
"""

import pytest

from crucible.failures.evidence_packet import FailureClass, FailureEvidencePacket
from crucible.runner.handoff_controller import HandoffController, HandoffDecision, Role
from crucible.state.attempt_state import AttemptState
from crucible.state.attempt_type import AttemptType


class TestHandoffController:
    """Test HandoffController."""
    
    def test_validation_pass_routes_to_review(self):
        """Validated pass routes to review."""
        decision = HandoffController.decide_handoff(
            current_state=AttemptState.VALIDATED_PASS,
            attempt_type=AttemptType.BUILD,
        )
        
        assert decision.to_role == Role.REVIEWER
        assert decision.attempt_type == AttemptType.REVIEW
    
    def test_validation_pass_repair_also_routes_to_review(self):
        """Repair pass also routes to review."""
        decision = HandoffController.decide_handoff(
            current_state=AttemptState.VALIDATED_PASS,
            attempt_type=AttemptType.REPAIR,
        )
        
        assert decision.to_role == Role.REVIEWER
        assert decision.attempt_type == AttemptType.REVIEW
    
    def test_validation_failure_routes_to_repair(self):
        """Validation failure routes to repair."""
        evidence = FailureEvidencePacket(
            failure_class=FailureClass.VALIDATION_FAILURE,
            attempt_id="attempt-1",
            criterion="test_criterion",
        )
        
        decision = HandoffController.decide_handoff(
            current_state=AttemptState.VALIDATED_FAIL,
            attempt_type=AttemptType.BUILD,
            failure_evidence=evidence,
        )
        
        assert decision.attempt_type == AttemptType.REPAIR
    
    def test_loop_detected_routes_to_debugger(self):
        """Loop detected routes to debugger."""
        evidence = FailureEvidencePacket(
            failure_class=FailureClass.LOOP_DETECTED,
            attempt_id="attempt-1",
        )
        
        decision = HandoffController.decide_handoff(
            current_state=AttemptState.VALIDATED_FAIL,
            attempt_type=AttemptType.REPAIR,
            failure_evidence=evidence,
        )
        
        assert decision.to_role == Role.DEBUGGER
        assert decision.attempt_type == AttemptType.DEBUG
    
    def test_first_failure_routes_to_repair(self):
        """First validation failure (no prior attempts) routes to repair."""
        evidence = FailureEvidencePacket(
            failure_class=FailureClass.VALIDATION_FAILURE,
            attempt_id="attempt-1",
            criterion="test_criterion",
            root_cause_hypothesis=None,
        )

        decision = HandoffController.decide_handoff(
            current_state=AttemptState.VALIDATED_FAIL,
            attempt_type=AttemptType.BUILD,
            failure_evidence=evidence,
        )

        # First failure goes to repair, not debugger
        assert decision.attempt_type == AttemptType.REPAIR

    def test_multiple_prior_failures_routes_to_debugger(self):
        """Multiple prior failures with same criterion routes to debugger."""
        evidence = FailureEvidencePacket(
            failure_class=FailureClass.VALIDATION_FAILURE,
            attempt_id="attempt-3",
            criterion="test_criterion",
            prior_attempts=["attempt-1", "attempt-2"],
            root_cause_hypothesis="some hypothesis",
        )
        
        decision = HandoffController.decide_handoff(
            current_state=AttemptState.VALIDATED_FAIL,
            attempt_type=AttemptType.REPAIR,
            failure_evidence=evidence,
        )
        
        assert decision.to_role == Role.DEBUGGER
    
    def test_review_accept_routes_to_complete(self):
        """Review accept routes to complete."""
        review_result = {"verdict": "accept"}
        
        decision = HandoffController.decide_handoff(
            current_state=AttemptState.VALIDATED_PASS,
            attempt_type=AttemptType.REVIEW,
            review_result=review_result,
        )
        
        assert decision.from_role == Role.REVIEWER
        # Accept means task can complete
    
    def test_review_reject_routes_to_repair(self):
        """Review reject routes to repair."""
        review_result = {"verdict": "reject", "rejection_type": "general"}
        
        decision = HandoffController.decide_handoff(
            current_state=AttemptState.VALIDATED_PASS,
            attempt_type=AttemptType.REVIEW,
            review_result=review_result,
        )
        
        assert decision.attempt_type == AttemptType.REPAIR
    
    def test_review_reject_missing_explanation_routes_to_debugger(self):
        """Review reject with missing causal explanation routes to debugger."""
        review_result = {
            "verdict": "reject",
            "rejection_type": "missing_causal_explanation",
        }
        
        decision = HandoffController.decide_handoff(
            current_state=AttemptState.VALIDATED_PASS,
            attempt_type=AttemptType.REVIEW,
            review_result=review_result,
        )
        
        assert decision.to_role == Role.DEBUGGER
        assert decision.attempt_type == AttemptType.DEBUG
    
    def test_partial_routes_to_salvage(self):
        """Partial output routes to salvage."""
        decision = HandoffController.decide_handoff(
            current_state=AttemptState.PARTIAL,
            attempt_type=AttemptType.BUILD,
        )
        
        assert decision.to_role == Role.SALVAGE
        assert decision.attempt_type == AttemptType.SALVAGE
    
    def test_default_routes_to_builder(self):
        """Default handoff routes to builder."""
        decision = HandoffController.decide_handoff(
            current_state=AttemptState.PENDING,
            attempt_type=AttemptType.BUILD,
        )
        
        assert decision.to_role == Role.BUILDER
        assert decision.attempt_type == AttemptType.BUILD
    
    def test_get_role_for_attempt_type(self):
        """Mapping from attempt type to role."""
        assert HandoffController.get_role_for_attempt_type(AttemptType.BUILD) == Role.BUILDER
        assert HandoffController.get_role_for_attempt_type(AttemptType.REPAIR) == Role.BUILDER
        assert HandoffController.get_role_for_attempt_type(AttemptType.DEBUG) == Role.DEBUGGER
        assert HandoffController.get_role_for_attempt_type(AttemptType.REVIEW) == Role.REVIEWER
        assert HandoffController.get_role_for_attempt_type(AttemptType.SALVAGE) == Role.SALVAGE
        assert HandoffController.get_role_for_attempt_type(AttemptType.INTEGRATE) == Role.INTEGRATOR
    
    def test_ambiguity_block_requires_user(self):
        """Ambiguity block requires user input."""
        evidence = FailureEvidencePacket(
            failure_class=FailureClass.AMBIGUITY_BLOCK,
            attempt_id="attempt-1",
        )
        
        decision = HandoffController.decide_handoff(
            current_state=AttemptState.VALIDATED_FAIL,
            attempt_type=AttemptType.BUILD,
            failure_evidence=evidence,
        )
        
        assert decision.requires_user_input is True
    
    def test_architecture_mismatch_blocks(self):
        """Architecture mismatch blocks."""
        evidence = FailureEvidencePacket(
            failure_class=FailureClass.ARCHITECTURE_MISMATCH,
            attempt_id="attempt-1",
        )
        
        decision = HandoffController.decide_handoff(
            current_state=AttemptState.VALIDATED_FAIL,
            attempt_type=AttemptType.BUILD,
            failure_evidence=evidence,
        )
        
        assert decision.requires_user_input is True
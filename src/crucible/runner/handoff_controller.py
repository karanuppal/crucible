"""
Role handoff controller for Crucible v5.4.

Implements deterministic transitions between Builder ↔ Reviewer ↔ Debugger ↔ Salvage ↔ Integrator.
"""

from dataclasses import dataclass
from enum import Enum
from typing import Optional

from crucible.failures.evidence_packet import FailureClass, FailureEvidencePacket
from crucible.failures.next_action_selector import NextAction
from crucible.state.attempt_state import AttemptState
from crucible.state.attempt_type import AttemptType


class Role(str, Enum):
    """Roles in the handoff system."""
    
    BUILDER = "builder"
    REVIEWER = "reviewer"
    DEBUGGER = "debugger"
    SALVAGE = "salvage"
    INTEGRATOR = "integrator"


@dataclass
class HandoffDecision:
    """Result of a handoff decision."""
    
    from_role: Role
    to_role: Role
    attempt_type: AttemptType
    reasoning: str
    requires_user_input: bool = False


class HandoffController:
    """
    Deterministic role handoff logic.
    
    Implements spec Section 8: Builder / Reviewer / Debugger / Salvage / Integrator rules.
    """
    
    # Mapping from attempt states to handoff decisions
    @classmethod
    def decide_handoff(
        cls,
        current_state: AttemptState,
        attempt_type: AttemptType,
        failure_evidence: Optional[FailureEvidencePacket] = None,
        review_result: Optional[dict] = None,
    ) -> HandoffDecision:
        """
        Determine the next handoff based on current state.
        
        Args:
            current_state: Current attempt state
            attempt_type: Type of attempt that just completed
            failure_evidence: Evidence if validation failed
            review_result: Review output if review just completed
            
        Returns:
            HandoffDecision for next step
        """
        # REVIEW RESULT takes priority - review just completed
        if review_result is not None:
            return cls._handle_review_result(review_result)
        
        # After BUILD passes validation -> review or complete
        if current_state == AttemptState.VALIDATED_PASS:
            return cls._handle_validation_pass(attempt_type)
        
        # After BUILD fails validation -> classify failure, route to repair/debug/salvage
        if current_state == AttemptState.VALIDATED_FAIL:
            return cls._handle_validation_fail(attempt_type, failure_evidence)
        
        # Partial output handling
        if current_state == AttemptState.PARTIAL:
            return cls._handle_partial(attempt_type)
        
        # Default: start with builder
        return cls._default_handoff()
    
    @classmethod
    def _handle_validation_pass(cls, attempt_type: AttemptType) -> HandoffDecision:
        """Handle validated pass - route to review or complete."""
        if attempt_type in (AttemptType.BUILD, AttemptType.REPAIR, AttemptType.REVALIDATE):
            return HandoffDecision(
                from_role=Role.BUILDER,
                to_role=Role.REVIEWER,
                attempt_type=AttemptType.REVIEW,
                reasoning=f"{attempt_type.value} validated_pass → review gate",
            )
        
        return HandoffDecision(
            from_role=Role.BUILDER,
            to_role=Role.BUILDER,
            attempt_type=AttemptType.BUILD,
            reasoning="default to builder",
        )
    
    @classmethod
    def _handle_validation_fail(
        cls,
        attempt_type: AttemptType,
        failure_evidence: Optional[FailureEvidencePacket],
    ) -> HandoffDecision:
        """Handle validation failure - route based on failure class."""
        if failure_evidence is None:
            # No evidence - default to repair
            return HandoffDecision(
                from_role=Role.BUILDER,
                to_role=Role.BUILDER,
                attempt_type=AttemptType.REPAIR,
                reasoning="validation failed, no evidence → repair",
            )
        
        failure_class = failure_evidence.failure_class
        
        # Handle specific failure classes first
        # Loop detected - always debugger
        if failure_class == FailureClass.LOOP_DETECTED:
            return HandoffDecision(
                from_role=Role.BUILDER,
                to_role=Role.DEBUGGER,
                attempt_type=AttemptType.DEBUG,
                reasoning=f"{failure_class.value} → debugger",
            )
        
        # Architecture mismatch - block
        if failure_class == FailureClass.ARCHITECTURE_MISMATCH:
            return HandoffDecision(
                from_role=Role.BUILDER,
                to_role=Role.BUILDER,
                attempt_type=AttemptType.BUILD,
                reasoning="architecture mismatch → blocked",
                requires_user_input=True,
            )
        
        # User required for ambiguity/missing dependency
        if failure_class in (FailureClass.AMBIGUITY_BLOCK, FailureClass.MISSING_DEPENDENCY):
            return HandoffDecision(
                from_role=Role.BUILDER,
                to_role=Role.BUILDER,
                attempt_type=AttemptType.REPAIR,
                reasoning=f"{failure_class.value} → awaiting user",
                requires_user_input=True,
            )
        
        # For VALIDATION_FAILURE and MODEL_LIMITATION:
        # Check if debugger is required (repeated failures or unclear root cause)
        if failure_class in (FailureClass.VALIDATION_FAILURE, FailureClass.MODEL_LIMITATION):
            if cls._requires_debugger(failure_evidence):
                return HandoffDecision(
                    from_role=Role.BUILDER,
                    to_role=Role.DEBUGGER,
                    attempt_type=AttemptType.DEBUG,
                    reasoning=f"{failure_class.value} → debugger (root cause unclear)",
                )
            # Otherwise route to repair
            return HandoffDecision(
                from_role=Role.BUILDER,
                to_role=Role.BUILDER,
                attempt_type=AttemptType.REPAIR,
                reasoning=f"{failure_class.value} → repair",
            )
        
        # Default to repair
        return HandoffDecision(
            from_role=Role.BUILDER,
            to_role=Role.BUILDER,
            attempt_type=AttemptType.REPAIR,
            reasoning=f"{failure_class.value} → repair",
        )
    
    @classmethod
    def _requires_debugger(cls, evidence: FailureEvidencePacket) -> bool:
        """Determine if failure requires debugger vs repair."""
        # If prior attempts have same criterion failing (2+), need debugger
        # This indicates repeated failure on the same issue
        if len(evidence.prior_attempts) >= 2:
            return True
        
        # If root cause is explicitly unknown after some investigation
        if evidence.root_cause_hypothesis == "unknown":
            return True
        
        return False
    
    @classmethod
    def _handle_review_result(cls, review_result: dict) -> HandoffDecision:
        """Handle review completion - accept, reject, or escalate."""
        verdict = review_result.get("verdict", "reject")
        
        if verdict == "accept":
            return HandoffDecision(
                from_role=Role.REVIEWER,
                to_role=Role.BUILDER,
                attempt_type=AttemptType.BUILD,
                reasoning="review accepted → complete",
            )
        
        # Reject - route based on rejection reason
        rejection_type = review_result.get("rejection_type", "general")
        
        if rejection_type == "missing_causal_explanation":
            return HandoffDecision(
                from_role=Role.REVIEWER,
                to_role=Role.DEBUGGER,
                attempt_type=AttemptType.DEBUG,
                reasoning="review reject: missing root cause → debugger",
            )
        
        if rejection_type == "superficial_fix":
            return HandoffDecision(
                from_role=Role.REVIEWER,
                to_role=Role.BUILDER,
                attempt_type=AttemptType.REPAIR,
                reasoning="review reject: superficial → repair",
            )
        
        # Default reject to repair
        return HandoffDecision(
            from_role=Role.REVIEWER,
            to_role=Role.BUILDER,
            attempt_type=AttemptType.REPAIR,
            reasoning=f"review reject ({rejection_type}) → repair",
        )
    
    @classmethod
    def _handle_partial(cls, attempt_type: AttemptType) -> HandoffDecision:
        """Handle partial output - salvage or integrate."""
        return HandoffDecision(
            from_role=Role.BUILDER,
            to_role=Role.SALVAGE,
            attempt_type=AttemptType.SALVAGE,
            reasoning=f"{attempt_type.value} partial → salvage",
        )
    
    @classmethod
    def _default_handoff(cls) -> HandoffDecision:
        """Default handoff - start with builder."""
        return HandoffDecision(
            from_role=Role.BUILDER,
            to_role=Role.BUILDER,
            attempt_type=AttemptType.BUILD,
            reasoning="default: start with builder",
        )
    
    @classmethod
    def get_role_for_attempt_type(cls, attempt_type: AttemptType) -> Role:
        """Map attempt type to role."""
        mapping = {
            AttemptType.BUILD: Role.BUILDER,
            AttemptType.REPAIR: Role.BUILDER,
            AttemptType.DEBUG: Role.DEBUGGER,
            AttemptType.REVIEW: Role.REVIEWER,
            AttemptType.SALVAGE: Role.SALVAGE,
            AttemptType.INTEGRATE: Role.INTEGRATOR,
            AttemptType.REVALIDATE: Role.REVIEWER,
        }
        return mapping.get(attempt_type, Role.BUILDER)
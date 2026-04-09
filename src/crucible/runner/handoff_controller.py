"""Control-plane handoff controller for Crucible v6.1.

Keeps loop control coarse and deterministic:
- retryable -> continue autonomously
- needs_user_input -> pause autonomous execution
- stuck_or_repeating -> force a materially different autonomous strategy
- terminal_nonrecoverable -> stop the loop
"""

from dataclasses import dataclass
from enum import Enum
from typing import Optional

from crucible.failures.evidence_packet import FailureClass, FailureEvidencePacket
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
    """Result of a control-plane handoff decision."""

    from_role: Role
    to_role: Role
    attempt_type: AttemptType | None
    reasoning: str
    requires_user_input: bool = False
    terminal: bool = False


class HandoffController:
    """Deterministic v6.1 loop-control decisions."""

    @classmethod
    def decide_handoff(
        cls,
        current_state: AttemptState,
        attempt_type: AttemptType,
        failure_evidence: Optional[FailureEvidencePacket] = None,
        review_result: Optional[dict] = None,
    ) -> HandoffDecision:
        """Determine the next control-plane step."""
        if review_result is not None:
            return cls._handle_review_result(review_result)

        if current_state == AttemptState.VALIDATED_PASS:
            return cls._handle_validation_pass(attempt_type)

        if current_state == AttemptState.VALIDATED_FAIL:
            return cls._handle_validation_fail(failure_evidence)

        if current_state == AttemptState.PARTIAL:
            return cls._handle_partial(attempt_type)

        return cls._default_handoff()

    @classmethod
    def _handle_validation_pass(cls, attempt_type: AttemptType) -> HandoffDecision:
        if attempt_type in (AttemptType.BUILD, AttemptType.REPAIR, AttemptType.REVALIDATE):
            return HandoffDecision(
                from_role=cls.get_role_for_attempt_type(attempt_type),
                to_role=Role.REVIEWER,
                attempt_type=AttemptType.REVIEW,
                reasoning=f"{attempt_type.value} validated_pass -> review gate",
            )

        return HandoffDecision(
            from_role=cls.get_role_for_attempt_type(attempt_type),
            to_role=Role.BUILDER,
            attempt_type=AttemptType.BUILD,
            reasoning="validated pass outside build/repair flow -> builder",
        )

    @classmethod
    def _handle_validation_fail(
        cls,
        failure_evidence: Optional[FailureEvidencePacket],
    ) -> HandoffDecision:
        if failure_evidence is None:
            return HandoffDecision(
                from_role=Role.BUILDER,
                to_role=Role.BUILDER,
                attempt_type=AttemptType.REPAIR,
                reasoning="validation failed with no evidence -> repair",
            )

        failure_class = failure_evidence.failure_class

        if failure_class == FailureClass.NEEDS_USER_INPUT:
            return HandoffDecision(
                from_role=Role.BUILDER,
                to_role=Role.BUILDER,
                attempt_type=None,
                reasoning="needs_user_input -> pause autonomous loop awaiting targeted human input",
                requires_user_input=True,
            )

        if failure_class == FailureClass.TERMINAL_NONRECOVERABLE:
            return HandoffDecision(
                from_role=Role.BUILDER,
                to_role=Role.BUILDER,
                attempt_type=None,
                reasoning="terminal_nonrecoverable -> stop loop with evidence-backed terminal outcome",
                terminal=True,
            )

        if failure_class == FailureClass.STUCK_OR_REPEATING:
            return HandoffDecision(
                from_role=Role.BUILDER,
                to_role=Role.DEBUGGER,
                attempt_type=AttemptType.DEBUG,
                reasoning="stuck_or_repeating -> force materially different debug strategy",
            )

        if failure_class == FailureClass.RETRYABLE:
            if cls._requires_material_strategy_shift(failure_evidence):
                return HandoffDecision(
                    from_role=Role.BUILDER,
                    to_role=Role.DEBUGGER,
                    attempt_type=AttemptType.DEBUG,
                    reasoning="retryable repeated failure -> deep recovery via debug",
                )
            return HandoffDecision(
                from_role=Role.BUILDER,
                to_role=Role.BUILDER,
                attempt_type=AttemptType.REPAIR,
                reasoning="retryable -> continue autonomously with repair",
            )

        return HandoffDecision(
            from_role=Role.BUILDER,
            to_role=Role.BUILDER,
            attempt_type=AttemptType.REPAIR,
            reasoning=f"{failure_class.value} -> repair",
        )

    @classmethod
    def _requires_material_strategy_shift(cls, evidence: FailureEvidencePacket) -> bool:
        """Escalate repeated retryable failures into a different autonomous strategy."""
        return evidence.repeated_failure or len(evidence.prior_attempts) >= 2

    @classmethod
    def _handle_review_result(cls, review_result: dict) -> HandoffDecision:
        verdict = review_result.get("verdict", "reject")

        if verdict == "accept":
            return HandoffDecision(
                from_role=Role.REVIEWER,
                to_role=Role.BUILDER,
                attempt_type=AttemptType.BUILD,
                reasoning="review accepted -> complete/build flow ends cleanly",
            )

        rejection_type = review_result.get("rejection_type", "general")

        if rejection_type == "missing_causal_explanation":
            return HandoffDecision(
                from_role=Role.REVIEWER,
                to_role=Role.DEBUGGER,
                attempt_type=AttemptType.DEBUG,
                reasoning="review reject: missing causal explanation -> debug",
            )

        return HandoffDecision(
            from_role=Role.REVIEWER,
            to_role=Role.BUILDER,
            attempt_type=AttemptType.REPAIR,
            reasoning=f"review reject ({rejection_type}) -> repair",
        )

    @classmethod
    def _handle_partial(cls, attempt_type: AttemptType) -> HandoffDecision:
        return HandoffDecision(
            from_role=cls.get_role_for_attempt_type(attempt_type),
            to_role=Role.SALVAGE,
            attempt_type=AttemptType.SALVAGE,
            reasoning=f"{attempt_type.value} partial -> salvage",
        )

    @classmethod
    def _default_handoff(cls) -> HandoffDecision:
        return HandoffDecision(
            from_role=Role.BUILDER,
            to_role=Role.BUILDER,
            attempt_type=AttemptType.BUILD,
            reasoning="default: start with builder",
        )

    @classmethod
    def get_role_for_attempt_type(cls, attempt_type: AttemptType) -> Role:
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

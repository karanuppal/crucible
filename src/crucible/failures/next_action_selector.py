"""Deterministic next-action selector for Crucible v5.4."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from crucible.failures.evidence_packet import FailureClass, FailureEvidencePacket
from crucible.state.attempt_type import AttemptType


class NextAction(str, Enum):
    BUILD = "build"
    REPAIR = "repair"
    DEBUG = "debug"
    REVIEW = "review"
    SALVAGE = "salvage"
    INTEGRATE = "integrate"
    REVALIDATE = "revalidate"
    AWAITING_USER = "awaiting_user"
    BLOCKED = "blocked"
    COMPLETE = "complete"
    SPLIT = "split"
    ESCALATE = "escalate"
    ENVIRONMENT_FIX = "environment_fix"
    ARCHITECTURE_PROPOSAL = "architecture_proposal"


@dataclass
class NextActionDecision:
    action: NextAction
    attempt_type: AttemptType | None = None
    reasoning: str = ""
    budget_consumed: bool = True
    requires_user_input: bool = False
    question_packet: dict[str, Any] | None = None
    rule_fired: str = ""
    rejected_alternatives: list[str] = field(default_factory=list)
    inputs_considered: dict[str, Any] = field(default_factory=dict)


class NextActionSelector:
    _ACTION_MATRIX = {
        FailureClass.AMBIGUITY_BLOCK: (NextAction.AWAITING_USER, None, False, True),
        FailureClass.ENVIRONMENT_BLOCK: (NextAction.ENVIRONMENT_FIX, AttemptType.BUILD, False, False),
        FailureClass.MISSING_DEPENDENCY: (NextAction.AWAITING_USER, None, False, True),
        FailureClass.ARCHITECTURE_MISMATCH: (NextAction.BLOCKED, None, True, False),
        FailureClass.MODEL_LIMITATION: (NextAction.REPAIR, AttemptType.REPAIR, True, False),
        FailureClass.VALIDATION_FAILURE: (NextAction.REPAIR, AttemptType.REPAIR, True, False),
        FailureClass.INTEGRATION_CONFLICT: (NextAction.INTEGRATE, AttemptType.INTEGRATE, True, False),
        FailureClass.LOOP_DETECTED: (NextAction.DEBUG, AttemptType.DEBUG, True, False),
    }

    @classmethod
    def select(
        cls,
        evidence: FailureEvidencePacket,
        budgets_remaining: dict[str, int],
        *,
        rejection_ledger: list[dict[str, Any]] | None = None,
        attempt_history: list[dict[str, Any]] | None = None,
        workspace_policy: str | None = None,
    ) -> NextActionDecision:
        rejection_ledger = rejection_ledger or []
        attempt_history = attempt_history or []
        base_action, attempt_type, consumes_budget, requires_user = cls._ACTION_MATRIX.get(
            evidence.failure_class,
            (NextAction.BLOCKED, None, False, False),
        )
        rule_fired = f"matrix:{evidence.failure_class.value}"
        rejected_alternatives: list[str] = []

        if evidence.failure_class == FailureClass.VALIDATION_FAILURE:
            repeated_signature = sum(
                1 for item in attempt_history if item.get("signature") == evidence.signature
            )
            if repeated_signature >= 2 or len(evidence.prior_attempts) >= 2:
                base_action = NextAction.DEBUG
                attempt_type = AttemptType.DEBUG
                rule_fired = "validation_failure:repeated_signature->debug"
                rejected_alternatives.append("repair")

        if evidence.failure_class == FailureClass.MODEL_LIMITATION and len(evidence.prior_attempts) >= 2:
            base_action = NextAction.DEBUG
            attempt_type = AttemptType.DEBUG
            rule_fired = "model_limitation:escalate_to_debug"
            rejected_alternatives.append("repair")

        if evidence.failure_class == FailureClass.ARCHITECTURE_MISMATCH:
            if any(entry.get("action") == "revise_plan" for entry in rejection_ledger):
                base_action = NextAction.ESCALATE
                rule_fired = "architecture_mismatch:escalate_after_prior_revision"
            else:
                rejected_alternatives.append("repair")

        if evidence.failure_class == FailureClass.LOOP_DETECTED and workspace_policy == "integration_only_fresh_merge":
            rejected_alternatives.append("salvage")

        if attempt_type and consumes_budget:
            budget_key = cls._attempt_type_to_budget_key(attempt_type)
            if budgets_remaining.get(budget_key, 0) <= 0:
                return NextActionDecision(
                    action=NextAction.BLOCKED,
                    reasoning=f"{budget_key} exhausted for {evidence.failure_class.value}",
                    budget_consumed=False,
                    rule_fired=f"budget_exhausted:{budget_key}",
                    rejected_alternatives=[base_action.value],
                    inputs_considered=cls._inputs(evidence, budgets_remaining, rejection_ledger, attempt_history, workspace_policy),
                )

        question_packet = cls._build_question_packet(evidence) if requires_user else None
        reasoning = f"{rule_fired}: {evidence.failure_class.value} -> {base_action.value}"
        if evidence.root_cause_hypothesis:
            reasoning += f" (hypothesis: {evidence.root_cause_hypothesis})"

        return NextActionDecision(
            action=base_action,
            attempt_type=attempt_type,
            reasoning=reasoning,
            budget_consumed=consumes_budget,
            requires_user_input=requires_user,
            question_packet=question_packet,
            rule_fired=rule_fired,
            rejected_alternatives=rejected_alternatives,
            inputs_considered=cls._inputs(evidence, budgets_remaining, rejection_ledger, attempt_history, workspace_policy),
        )

    @staticmethod
    def _inputs(
        evidence: FailureEvidencePacket,
        budgets_remaining: dict[str, int],
        rejection_ledger: list[dict[str, Any]],
        attempt_history: list[dict[str, Any]],
        workspace_policy: str | None,
    ) -> dict[str, Any]:
        return {
            "packet": evidence.to_next_action_input(),
            "budgets_remaining": dict(budgets_remaining),
            "rejection_ledger_size": len(rejection_ledger),
            "attempt_history_size": len(attempt_history),
            "workspace_policy": workspace_policy,
        }

    @staticmethod
    def _attempt_type_to_budget_key(attempt_type: AttemptType) -> str:
        return {
            AttemptType.BUILD: "build_attempt_budget",
            AttemptType.REPAIR: "repair_attempt_budget",
            AttemptType.DEBUG: "debug_attempt_budget",
            AttemptType.REVIEW: "review_rejection_budget",
            AttemptType.SALVAGE: "salvage_attempt_budget",
            AttemptType.INTEGRATE: "integration_budget",
            AttemptType.REVALIDATE: "repair_attempt_budget",
        }.get(attempt_type, "repair_attempt_budget")

    @staticmethod
    def _build_question_packet(evidence: FailureEvidencePacket) -> dict[str, Any]:
        if evidence.failure_class == FailureClass.AMBIGUITY_BLOCK:
            question = "The request is ambiguous. What specific behavior do you want?"
            qtype = "clarification_needed"
        elif evidence.failure_class == FailureClass.MISSING_DEPENDENCY:
            question = "Missing dependency required to proceed. How would you like to provide it?"
            qtype = "dependency_required"
        else:
            question = f"Blocked by failure class: {evidence.failure_class.value}"
            qtype = "general"
        return {
            "type": qtype,
            "question": question,
            "evidence_refs": list(evidence.evidence_refs),
            "task_id": evidence.task_id,
            "attempt_id": evidence.attempt_id,
        }

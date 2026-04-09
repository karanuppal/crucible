"""Deterministic next-action selector for Crucible v6.1."""

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
    budget_key: str | None = None


class NextActionSelector:
    _ACTION_MATRIX = {
        FailureClass.RETRYABLE: (NextAction.REPAIR, AttemptType.REPAIR, True, False, "repair_attempt_budget"),
        FailureClass.NEEDS_USER_INPUT: (NextAction.AWAITING_USER, None, False, True, None),
        FailureClass.STUCK_OR_REPEATING: (NextAction.DEBUG, AttemptType.DEBUG, True, False, "deep_recovery_budget"),
        FailureClass.TERMINAL_NONRECOVERABLE: (NextAction.BLOCKED, None, False, False, None),
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
        base_action, attempt_type, consumes_budget, requires_user, budget_key = cls._ACTION_MATRIX.get(
            evidence.failure_class,
            (NextAction.BLOCKED, None, False, False, None),
        )
        rule_fired = f"matrix:{evidence.failure_class.value}"
        rejected_alternatives: list[str] = []

        if evidence.failure_class == FailureClass.RETRYABLE:
            if "integration_hint" in evidence.hints:
                base_action = NextAction.INTEGRATE
                attempt_type = AttemptType.INTEGRATE
                budget_key = "integration_attempt_budget"
                rule_fired = "retryable:integration_hint->integrate"
            elif "environment_hint" in evidence.hints:
                base_action = NextAction.REPAIR
                attempt_type = AttemptType.REPAIR
                budget_key = "repair_attempt_budget"
                rule_fired = "retryable:environment_hint->repair"
            elif sum(1 for item in attempt_history if item.get("signature") == evidence.signature) >= 2 or evidence.repeated_failure:
                base_action = NextAction.DEBUG
                attempt_type = AttemptType.DEBUG
                budget_key = "deep_recovery_budget"
                rule_fired = "retryable:repeated_signature->deep_recovery"
                rejected_alternatives.append("repair")

        if evidence.failure_class == FailureClass.STUCK_OR_REPEATING:
            if evidence.progress_made and budgets_remaining.get("repair_attempt_budget", 0) > 0:
                rejected_alternatives.append("blocked")
            if workspace_policy == "integration_only_fresh_merge":
                rejected_alternatives.append("salvage")

        if evidence.failure_class == FailureClass.TERMINAL_NONRECOVERABLE:
            question_packet = None
            reasoning = f"{rule_fired}: terminal evidence-backed stop"
            return NextActionDecision(
                action=NextAction.BLOCKED,
                attempt_type=None,
                reasoning=reasoning,
                budget_consumed=False,
                requires_user_input=False,
                question_packet=question_packet,
                rule_fired=rule_fired,
                rejected_alternatives=rejected_alternatives,
                inputs_considered=cls._inputs(evidence, budgets_remaining, rejection_ledger, attempt_history, workspace_policy),
                budget_key=budget_key,
            )

        if budget_key and budgets_remaining.get(budget_key, 0) <= 0:
            return NextActionDecision(
                action=NextAction.BLOCKED,
                reasoning=f"{budget_key} exhausted for {evidence.failure_class.value}",
                budget_consumed=False,
                rule_fired=f"budget_exhausted:{budget_key}",
                rejected_alternatives=[base_action.value],
                inputs_considered=cls._inputs(evidence, budgets_remaining, rejection_ledger, attempt_history, workspace_policy),
                budget_key=budget_key,
            )

        question_packet = cls._build_question_packet(evidence) if requires_user else None
        reasoning = f"{rule_fired}: {evidence.failure_class.value} -> {base_action.value}"
        if evidence.root_cause_hypothesis:
            reasoning += f" (hypothesis: {evidence.root_cause_hypothesis})"
        if evidence.hints:
            reasoning += f" [hints: {', '.join(sorted(evidence.hints))}]"

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
            budget_key=budget_key,
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
            AttemptType.INTEGRATE: "integration_attempt_budget",
            AttemptType.REVALIDATE: "repair_attempt_budget",
        }.get(attempt_type, "repair_attempt_budget")

    @staticmethod
    def _build_question_packet(evidence: FailureEvidencePacket) -> dict[str, Any]:
        requirement = dict(evidence.metadata.get("required_user_input") or {})
        qtype = str(requirement.get("type") or "user_input_required")
        target = requirement.get("target")
        if target is not None:
            target = str(target)

        if qtype == "credential_required":
            question = "Missing credential or secret required to proceed."
            if target:
                question = f"Missing credential or secret required to proceed: {target}."
        elif qtype == "approval_required":
            question = "Explicit approval required before continuing."
            if target:
                question = f"Explicit approval required before continuing: {target}."
        elif qtype == "clarification_needed":
            question = "The request is ambiguous. What specific behavior do you want?"
            if target:
                question = f"Clarification required before continuing: {target}."
        else:
            question = "Human input required to continue."
            if target:
                question = f"Human input required to continue: {target}."

        if not requirement:
            if "credential_hint" in evidence.hints:
                qtype = "credential_required"
                question = "Missing credential or secret required to proceed."
            elif "approval_hint" in evidence.hints:
                qtype = "approval_required"
                question = "Explicit approval required before continuing."
            elif "ambiguity_hint" in evidence.hints:
                qtype = "clarification_needed"
                question = "The request is ambiguous. What specific behavior do you want?"

        packet = {
            "type": qtype,
            "question": question,
            "evidence_refs": list(evidence.evidence_refs),
            "task_id": evidence.task_id,
            "attempt_id": evidence.attempt_id,
        }
        if target:
            packet["target"] = target
        if requirement.get("source"):
            packet["source"] = requirement["source"]
        return packet

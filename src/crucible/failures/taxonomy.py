"""Thin failure taxonomy for Crucible v6.1.

The control plane answers only four questions:
- keep going autonomously?
- ask the user?
- force a materially different strategy?
- stop?
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class FailureClass(str, Enum):
    RETRYABLE = "retryable"
    NEEDS_USER_INPUT = "needs_user_input"
    STUCK_OR_REPEATING = "stuck_or_repeating"
    TERMINAL_NONRECOVERABLE = "terminal_nonrecoverable"


class NextAction(str, Enum):
    CONTINUE_AUTONOMOUSLY = "continue_autonomously"
    ASK_USER = "ask_user"
    FORCE_STRATEGY_SHIFT = "force_strategy_shift"
    STOP_WITH_EVIDENCE = "stop_with_evidence"
    SAFE_FALLBACK = "safe_fallback"


_FAILURE_ACTION_MAP: dict[FailureClass, NextAction] = {
    FailureClass.RETRYABLE: NextAction.CONTINUE_AUTONOMOUSLY,
    FailureClass.NEEDS_USER_INPUT: NextAction.ASK_USER,
    FailureClass.STUCK_OR_REPEATING: NextAction.FORCE_STRATEGY_SHIFT,
    FailureClass.TERMINAL_NONRECOVERABLE: NextAction.STOP_WITH_EVIDENCE,
}

_NON_RETRY_CONSUMING: set[FailureClass] = {
    FailureClass.NEEDS_USER_INPUT,
}


@dataclass
class FailureClassification:
    failure_class: FailureClass
    next_action: NextAction
    consumes_retry_budget: bool
    description: str = ""
    evidence: str = ""


def classify_failure(
    failure_class: FailureClass | str,
    description: str = "",
    evidence: str = "",
) -> FailureClassification:
    if isinstance(failure_class, str):
        try:
            failure_class = FailureClass(failure_class)
        except ValueError:
            return FailureClassification(
                failure_class=FailureClass.STUCK_OR_REPEATING,
                next_action=NextAction.SAFE_FALLBACK,
                consumes_retry_budget=False,
                description=f"Unknown failure class: {failure_class}. Routed to safe fallback.",
                evidence=evidence,
            )

    next_action = _FAILURE_ACTION_MAP.get(failure_class, NextAction.SAFE_FALLBACK)
    consumes = failure_class not in _NON_RETRY_CONSUMING
    return FailureClassification(
        failure_class=failure_class,
        next_action=next_action,
        consumes_retry_budget=consumes,
        description=description,
        evidence=evidence,
    )


def get_next_action(failure_class: FailureClass) -> NextAction:
    return _FAILURE_ACTION_MAP.get(failure_class, NextAction.SAFE_FALLBACK)


def consumes_retry_budget(failure_class: FailureClass) -> bool:
    return failure_class not in _NON_RETRY_CONSUMING

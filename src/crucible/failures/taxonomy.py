"""Phase 1: Failure taxonomy and classification.

From the spec (§13):
- 8 failure classes with deterministic next actions
- Unknown failures route to safe fallback
- Budget semantics: environment/dependency failures don't consume task retry budget
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any


class FailureClass(str, Enum):
    AMBIGUITY_BLOCK = "ambiguity_block"
    ENVIRONMENT_BLOCK = "environment_block"
    MISSING_DEPENDENCY = "missing_dependency"
    ARCHITECTURE_MISMATCH = "architecture_mismatch"
    MODEL_LIMITATION = "model_limitation"
    VALIDATION_FAILURE = "validation_failure"
    INTEGRATION_CONFLICT = "integration_conflict"
    LOOP_DETECTED = "loop_detected"


class NextAction(str, Enum):
    ASK_USER = "ask_user"
    FIX_ENVIRONMENT = "fix_environment"
    REQUEST_DEPENDENCY = "request_dependency"
    PROPOSE_REVISION = "propose_revision"
    CHANGE_ROLE_MODEL_BACKEND = "change_role_model_backend"
    REPAIR_FROM_EVIDENCE = "repair_from_evidence"
    ROUTE_TO_INTEGRATOR = "route_to_integrator"
    TRIP_CIRCUIT_BREAKER = "trip_circuit_breaker"
    SAFE_FALLBACK = "safe_fallback"


# Deterministic mapping: failure class → required next action
_FAILURE_ACTION_MAP: dict[FailureClass, NextAction] = {
    FailureClass.AMBIGUITY_BLOCK: NextAction.ASK_USER,
    FailureClass.ENVIRONMENT_BLOCK: NextAction.FIX_ENVIRONMENT,
    FailureClass.MISSING_DEPENDENCY: NextAction.REQUEST_DEPENDENCY,
    FailureClass.ARCHITECTURE_MISMATCH: NextAction.PROPOSE_REVISION,
    FailureClass.MODEL_LIMITATION: NextAction.CHANGE_ROLE_MODEL_BACKEND,
    FailureClass.VALIDATION_FAILURE: NextAction.REPAIR_FROM_EVIDENCE,
    FailureClass.INTEGRATION_CONFLICT: NextAction.ROUTE_TO_INTEGRATOR,
    FailureClass.LOOP_DETECTED: NextAction.TRIP_CIRCUIT_BREAKER,
}

# Failure classes that should NOT consume task retry budget
_NON_RETRY_CONSUMING: set[FailureClass] = {
    FailureClass.ENVIRONMENT_BLOCK,
    FailureClass.MISSING_DEPENDENCY,
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
    """Classify a failure and determine the required next action.
    
    Args:
        failure_class: the failure class (enum or string value)
        description: human-readable description of the failure
        evidence: evidence that led to this classification
    
    Returns:
        FailureClassification with deterministic next action
    
    If the failure_class is unknown, routes to SAFE_FALLBACK.
    """
    # Handle string input
    if isinstance(failure_class, str):
        try:
            failure_class = FailureClass(failure_class)
        except ValueError:
            return FailureClassification(
                failure_class=FailureClass.LOOP_DETECTED,  # closest safe bucket
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
    """Get the deterministic next action for a failure class."""
    return _FAILURE_ACTION_MAP.get(failure_class, NextAction.SAFE_FALLBACK)


def consumes_retry_budget(failure_class: FailureClass) -> bool:
    """Check whether this failure class consumes the task retry budget."""
    return failure_class not in _NON_RETRY_CONSUMING

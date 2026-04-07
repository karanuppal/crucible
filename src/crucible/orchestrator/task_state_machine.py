"""Task state machine for Crucible v5.4."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class TaskTransition:
    from_state: str
    event: str
    to_state: str


class TaskStateMachine:
    TERMINAL_STATES = {"blocked", "complete", "awaiting_user"}
    _TRANSITIONS = {
        ("queued", "start_build"): "building",
        ("building", "start_validation"): "validating",
        ("validating", "validation_passed"): "reviewing",
        ("validating", "validation_failed_repair"): "repairing",
        ("validating", "validation_failed_debug"): "debugging",
        ("validating", "validation_failed_user"): "awaiting_user",
        ("validating", "validation_failed_blocked"): "blocked",
        ("validating", "partial_output"): "salvaging",
        ("repairing", "start_validation"): "validating",
        ("debugging", "start_validation"): "validating",
        ("salvaging", "start_validation"): "validating",
        ("reviewing", "review_accepted"): "complete",
        ("reviewing", "review_rejected_repair"): "repairing",
        ("reviewing", "review_rejected_debug"): "debugging",
        ("salvaging", "integrate_partial"): "integrating",
        ("integrating", "integration_passed"): "complete",
        ("integrating", "integration_failed_repair"): "repairing",
        ("integrating", "integration_failed_debug"): "debugging",
    }

    def can_transition(self, state: str, event: str) -> bool:
        return (state, event) in self._TRANSITIONS

    def transition(self, state: str, event: str) -> str:
        try:
            return self._TRANSITIONS[(state, event)]
        except KeyError as exc:
            raise ValueError(f"illegal transition: {state} + {event}") from exc

    def is_terminal(self, state: str) -> bool:
        return state in self.TERMINAL_STATES

    def describe(self, state: str, event: str) -> TaskTransition:
        return TaskTransition(from_state=state, event=event, to_state=self.transition(state, event))

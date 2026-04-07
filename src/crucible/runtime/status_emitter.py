"""Status emitter for Crucible v5.4."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from enum import Enum
from typing import Any


class EventType(str, Enum):
    TASK_STARTED = "task_started"
    ATTEMPT_STARTED = "attempt_started"
    ATTEMPT_COMPLETED = "attempt_completed"
    ATTEMPT_SUPERSEDED = "attempt_superseded"
    ATTEMPT_REJECTED = "attempt_rejected"
    VALIDATION_PASSED = "validation_passed"
    VALIDATION_FAILED = "validation_failed"
    REPAIR_SCHEDULED = "repair_scheduled"
    DEBUG_SCHEDULED = "debug_scheduled"
    SALVAGE_SCHEDULED = "salvage_scheduled"
    REVIEW_REQUESTED = "review_requested"
    REVIEW_ACCEPTED = "review_accepted"
    REVIEW_REJECTED = "review_rejected"
    WORKSPACE_CREATED = "workspace_created"
    WORKSPACE_INHERITED = "workspace_inherited"
    FAILURE_PACKET_CREATED = "failure_packet_created"
    NEXT_ACTION_SELECTED = "next_action_selected"
    TASK_COMPLETE = "task_complete"
    TASK_BLOCKED = "task_blocked"
    AWAITING_USER = "awaiting_user"
    BUDGET_EXHAUSTED = "budget_exhausted"
    CIRCUIT_BROKEN = "circuit_broken"


@dataclass
class StatusEvent:
    event_type: EventType
    task_id: str
    attempt_id: str | None = None
    timestamp: str = ""
    data: dict[str, Any] | None = None

    def __post_init__(self) -> None:
        if not self.timestamp:
            self.timestamp = datetime.now(UTC).isoformat()
        if self.data is None:
            self.data = {}

    def to_message(self) -> str:
        et = self.event_type
        d = self.data or {}
        messages = {
            EventType.TASK_STARTED: f"Task {self.task_id} started",
            EventType.ATTEMPT_STARTED: f"Attempt {self.attempt_id} started ({d.get('attempt_type', 'unknown')})",
            EventType.ATTEMPT_COMPLETED: f"Attempt {self.attempt_id} completed",
            EventType.ATTEMPT_SUPERSEDED: f"Attempt {self.attempt_id} superseded by {d.get('superseded_by', 'unknown')}",
            EventType.ATTEMPT_REJECTED: f"Attempt {self.attempt_id} rejected: {d.get('reason', 'unknown')}",
            EventType.VALIDATION_PASSED: f"Validation passed for {self.task_id}",
            EventType.VALIDATION_FAILED: f"Validation failed: {d.get('failure_class', 'unknown')}",
            EventType.REPAIR_SCHEDULED: f"Repair scheduled for {self.task_id}",
            EventType.DEBUG_SCHEDULED: f"Debug scheduled for {self.task_id}",
            EventType.SALVAGE_SCHEDULED: f"Salvage scheduled for {self.task_id}",
            EventType.REVIEW_REQUESTED: f"Review requested for {self.task_id}",
            EventType.REVIEW_ACCEPTED: f"Review accepted for {self.task_id}",
            EventType.REVIEW_REJECTED: f"Review rejected for {self.task_id}",
            EventType.WORKSPACE_CREATED: f"Workspace created for {self.task_id}",
            EventType.WORKSPACE_INHERITED: f"Workspace inherited for {self.task_id}",
            EventType.FAILURE_PACKET_CREATED: f"Failure packet captured for {self.task_id}",
            EventType.NEXT_ACTION_SELECTED: f"Next action for {self.task_id}: {d.get('action', 'unknown')}",
            EventType.TASK_COMPLETE: f"Task {self.task_id} completed successfully",
            EventType.TASK_BLOCKED: f"Task {self.task_id} is blocked: {d.get('reason', 'unknown')}",
            EventType.AWAITING_USER: f"Task {self.task_id} awaiting user input: {d.get('question', 'unknown')}",
            EventType.BUDGET_EXHAUSTED: f"Budget exhausted for {self.task_id}: {d.get('budget_type', 'unknown')}",
            EventType.CIRCUIT_BROKEN: f"Circuit breaker tripped for {self.task_id}: {d.get('reason', 'unknown')}",
        }
        return messages.get(et, f"Event: {et.value}")


class StatusEmitter:
    def __init__(self, enabled: bool = True):
        self.enabled = enabled
        self._events: list[StatusEvent] = []

    def emit(self, event: StatusEvent) -> None:
        if self.enabled:
            self._events.append(event)

    def emit_event(self, event_type: EventType, task_id: str, *, attempt_id: str | None = None, **data: Any) -> None:
        self.emit(StatusEvent(event_type=event_type, task_id=task_id, attempt_id=attempt_id, data=data))

    def emit_task_started(self, task_id: str):
        self.emit_event(EventType.TASK_STARTED, task_id)

    def emit_attempt_started(self, task_id: str, attempt_id: str, attempt_type: str):
        self.emit_event(EventType.ATTEMPT_STARTED, task_id, attempt_id=attempt_id, attempt_type=attempt_type)

    def emit_validation_passed(self, task_id: str, attempt_id: str):
        self.emit_event(EventType.VALIDATION_PASSED, task_id, attempt_id=attempt_id)

    def emit_validation_failed(self, task_id: str, attempt_id: str, failure_class: str):
        self.emit_event(EventType.VALIDATION_FAILED, task_id, attempt_id=attempt_id, failure_class=failure_class)

    def emit_task_complete(self, task_id: str):
        self.emit_event(EventType.TASK_COMPLETE, task_id)

    def emit_task_blocked(self, task_id: str, reason: str):
        self.emit_event(EventType.TASK_BLOCKED, task_id, reason=reason)

    def emit_awaiting_user(self, task_id: str, question: str):
        self.emit_event(EventType.AWAITING_USER, task_id, question=question)

    def get_events(self) -> list[StatusEvent]:
        return self._events.copy()

    def clear(self):
        self._events.clear()

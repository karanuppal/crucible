"""Phase 1: Append-only project ledger.

Design rules from spec:
- Append-only: no update/delete/overwrite of existing events
- Each event has: timestamp, projectId, buildId, taskId?, runId?, eventType, payload
- Supports persistence to disk (JSONL format)
- Recovery: corrupted tail record is detected and handled safely
"""

from __future__ import annotations

import json
import os
import time
import uuid
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Any


class EventType(str, Enum):
    SPEC_CREATED = "spec.created"
    SPEC_CLARIFIED = "spec.clarified"
    TASK_CREATED = "task.created"
    RUN_SPAWNED = "run.spawned"
    RUN_PROGRESS = "run.progress"
    RUN_TIMED_OUT = "run.timed_out"
    RUN_KILLED = "run.killed"
    RUN_SALVAGED = "run.salvaged"
    VALIDATION_COMPLETED = "validation.completed"
    INTEGRATION_COMPLETED = "integration.completed"
    FAILURE_CLASSIFIED = "failure.classified"
    BUILD_COMPLETED = "build.completed"


@dataclass
class LedgerEvent:
    timestamp: float
    projectId: str
    buildId: str
    eventType: EventType
    payload: dict[str, Any] = field(default_factory=dict)
    taskId: str = ""
    runId: str = ""
    eventId: str = field(default_factory=lambda: str(uuid.uuid4()))


class Ledger:
    """Append-only project ledger backed by a JSONL file."""

    def __init__(self, path: str) -> None:
        self._path = path
        self._events: list[LedgerEvent] = []
        if os.path.exists(path):
            self._load()

    def _load(self) -> None:
        """Load events from JSONL file, skipping corrupted tail records."""
        self._events = []
        with open(self._path, "r") as f:
            for line_num, line in enumerate(f, 1):
                line = line.strip()
                if not line:
                    continue
                try:
                    data = json.loads(line)
                    data["eventType"] = EventType(data["eventType"])
                    self._events.append(LedgerEvent(**data))
                except (json.JSONDecodeError, TypeError, ValueError, KeyError):
                    # Corrupted record — skip it but don't lose prior valid events
                    # This handles the "corrupted tail record" recovery requirement
                    continue

    def append(self, event: LedgerEvent) -> None:
        """Append an event to the ledger. Writes immediately to disk."""
        self._events.append(event)
        self._persist_event(event)

    def _persist_event(self, event: LedgerEvent) -> None:
        """Write a single event as a JSONL line."""
        data = asdict(event)
        data["eventType"] = event.eventType.value
        line = json.dumps(data, separators=(",", ":"))
        with open(self._path, "a") as f:
            f.write(line + "\n")

    def events(self) -> list[LedgerEvent]:
        """Return all events in append order."""
        return list(self._events)

    def events_by_type(self, event_type: EventType) -> list[LedgerEvent]:
        """Return events filtered by type."""
        return [e for e in self._events if e.eventType == event_type]

    def events_for_task(self, task_id: str) -> list[LedgerEvent]:
        """Return events for a specific task."""
        return [e for e in self._events if e.taskId == task_id]

    def events_for_run(self, run_id: str) -> list[LedgerEvent]:
        """Return events for a specific run."""
        return [e for e in self._events if e.runId == run_id]

    @property
    def count(self) -> int:
        return len(self._events)

    def create_event(
        self,
        project_id: str,
        build_id: str,
        event_type: EventType,
        payload: dict[str, Any] | None = None,
        task_id: str = "",
        run_id: str = "",
    ) -> LedgerEvent:
        """Create and append a new event."""
        event = LedgerEvent(
            timestamp=time.time(),
            projectId=project_id,
            buildId=build_id,
            eventType=event_type,
            payload=payload or {},
            taskId=task_id,
            runId=run_id,
        )
        self.append(event)
        return event

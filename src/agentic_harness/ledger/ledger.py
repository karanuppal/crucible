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

    def __init__(self, path: str, *, strict_integrity: bool = False) -> None:
        self._path = path
        self._events: list[LedgerEvent] = []
        self._next_seq: int = 0
        self._strict_integrity = strict_integrity
        if os.path.exists(path):
            self._load()

    def _load(self) -> None:
        """Load events from JSONL file.
        
        Corruption handling:
        - strict_integrity=True: corrupted non-tail records raise ValueError (fail-closed)
        - strict_integrity=False: corrupted records are skipped (lenient recovery)
        - Sequence numbers are validated for monotonic ordering when present
        """
        self._events = []
        lines: list[str] = []
        with open(self._path, "r") as f:
            lines = [l.strip() for l in f if l.strip()]
        
        last_seq = -1
        for line_idx, line in enumerate(lines):
            is_tail = (line_idx == len(lines) - 1)
            try:
                data = json.loads(line)
                data["eventType"] = EventType(data["eventType"])
                # Validate and strip sequence number if present
                # Sequence validation is always active — detects rewrite/forgery
                seq = data.pop("seq", None)
                if seq is not None:
                    if seq <= last_seq:
                        raise ValueError(f"Non-monotonic sequence: {seq} <= {last_seq}")
                    last_seq = seq
                self._events.append(LedgerEvent(**data))
            except (json.JSONDecodeError, TypeError, KeyError) as e:
                if self._strict_integrity and not is_tail:
                    raise ValueError(
                        f"Corrupted non-tail record at line {line_idx + 1}: {e}"
                    ) from e
                # Lenient mode or tail corruption: skip
                continue
        
        self._next_seq = last_seq + 1 if last_seq >= 0 else 0

    def append(self, event: LedgerEvent) -> None:
        """Append an event to the ledger. Writes immediately to disk."""
        self._events.append(event)
        self._persist_event(event)

    def _persist_event(self, event: LedgerEvent) -> None:
        """Write a single event as a JSONL line with sequence number."""
        data = asdict(event)
        data["eventType"] = event.eventType.value
        data["seq"] = self._next_seq
        self._next_seq += 1
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

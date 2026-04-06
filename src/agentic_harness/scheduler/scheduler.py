"""Phase 4: Adaptive scheduler and harness memory.

From spec (§12):
- Machine-aware scheduling
- Intensity-based concurrency limits
- Harness-owned memory store
- Lesson persistence and retrieval
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from enum import Enum

from agentic_harness.scheduler.machine_profile import MachineProfile, TaskIntensity


class SchedulerDecision(str, Enum):
    """Scheduling decision."""
    RUN_NOW = "run_now"
    QUEUE = "queue"
    DEFER = "defer"
    REJECT = "reject"


@dataclass
class ScheduleRequest:
    """A task scheduling request."""
    task_id: str
    intensity: TaskIntensity
    estimated_duration: float = 0.0
    priority: int = 0  # Higher = more important


@dataclass
class ScheduleResult:
    """Result of scheduling decision."""
    decision: SchedulerDecision
    reason: str
    queued_at: float | None = None


class AdaptiveScheduler:
    """Machine-aware adaptive scheduler.
    
    Heuristics:
    - Light tasks: run immediately up to concurrency limit
    - Medium tasks: check load, may queue
    - Heavy tasks: require explicit capacity, defer if busy
    """
    
    def __init__(self, profile: MachineProfile) -> None:
        self._profile = profile
        self._active: dict[str, float] = {}  # task_id -> start_time
        self._queue: list[ScheduleRequest] = []
    
    def decide(self, request: ScheduleRequest) -> ScheduleResult:
        """Decide scheduling for a task."""
        # Check current load
        active_count = len(self._active)
        max_concurrent = self._profile.recommended_max_concurrent
        
        if request.intensity == TaskIntensity.LIGHT:
            if active_count < max_concurrent * 2:  # Light tasks get more slack
                return ScheduleResult(SchedulerDecision.RUN_NOW, "light task, capacity available")
            else:
                return ScheduleResult(SchedulerDecision.QUEUE, "light but at capacity")
        
        elif request.intensity == TaskIntensity.MEDIUM:
            if active_count < max_concurrent:
                return ScheduleResult(SchedulerDecision.RUN_NOW, "medium task, within limit")
            else:
                return ScheduleResult(SchedulerDecision.QUEUE, "medium task, at capacity")
        
        else:  # HEAVY
            if active_count == 0:
                return ScheduleResult(SchedulerDecision.RUN_NOW, "heavy, machine idle")
            else:
                return ScheduleResult(SchedulerDecision.DEFER, "heavy task, machine busy")
    
    def start_task(self, task_id: str) -> None:
        """Mark task as started."""
        self._active[task_id] = time.time()
    
    def end_task(self, task_id: str) -> None:
        """Mark task as ended."""
        self._active.pop(task_id, None)
    
    def get_active_count(self) -> int:
        return len(self._active)
    
    def get_queue_length(self) -> int:
        return len(self._queue)


@dataclass
class Lesson:
    """A learned lesson for reuse."""
    id: str
    category: str  # "error_recovery", "approach", "pattern"
    problem: str
    solution: str
    evidence: str
    timestamp: float = field(default_factory=time.time)


class HarnessMemory:
    """Harness-owned memory store for lessons and context."""
    
    def __init__(self, storage_path: str | None = None) -> None:
        if storage_path is None:
            storage_path = os.path.expanduser("~/.agentic-harness/memory.jsonl")
        self._path = storage_path
        os.makedirs(os.path.dirname(storage_path), exist_ok=True)
    
    def store_lesson(self, lesson: Lesson) -> None:
        """Store a lesson."""
        with open(self._path, "a") as f:
            data = {
                "type": "lesson",
                "id": lesson.id,
                "category": lesson.category,
                "problem": lesson.problem,
                "solution": lesson.solution,
                "evidence": lesson.evidence,
                "timestamp": lesson.timestamp,
            }
            f.write(json.dumps(data) + "\n")
    
    def retrieve_lessons(
        self,
        category: str | None = None,
        limit: int = 10,
    ) -> list[Lesson]:
        """Retrieve recent lessons."""
        lessons = []
        if not os.path.exists(self._path):
            return lessons
        
        with open(self._path, "r") as f:
            lines = f.readlines()
        
        for line in reversed(lines):
            if len(lessons) >= limit:
                break
            try:
                data = json.loads(line)
                if data.get("type") != "lesson":
                    continue
                if category and data.get("category") != category:
                    continue
                lessons.append(Lesson(
                    id=data["id"],
                    category=data["category"],
                    problem=data["problem"],
                    solution=data["solution"],
                    evidence=data["evidence"],
                    timestamp=data["timestamp"],
                ))
            except json.JSONDecodeError:
                continue
        
        return lessons
    
    def inject_lessons(self, task_context: dict) -> list[str]:
        """Inject relevant lessons into task context."""
        # Get recent lessons
        lessons = self.retrieve_lessons(limit=5)
        
        # Inject as context strings
        injected = []
        for lesson in lessons:
            injected.append(f"[LESSON:{lesson.category}] {lesson.problem} → {lesson.solution}")
        
        return injected
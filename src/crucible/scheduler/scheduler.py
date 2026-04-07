"""Phase 4: Adaptive scheduler.

Schedules tasks while preserving CPU/memory headroom on the host.
Supports persistence and restart recovery.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Any

from crucible.scheduler.machine_profile import MachineProfile
from crucible.scheduler.intensity import Intensity, IntensityClassification


@dataclass
class TaskEntry:
    task_id: str
    intensity: Intensity
    cpu_cost: int  # estimated CPUs consumed
    memory_cost_gb: float  # estimated memory consumed
    queued_at: float = field(default_factory=time.time)
    started_at: float | None = None
    finished_at: float | None = None
    status: str = "queued"  # queued | running | finished | failed


# Resource costs per intensity
INTENSITY_COSTS: dict[Intensity, tuple[int, float]] = {
    Intensity.LIGHT: (1, 0.25),
    Intensity.MEDIUM: (1, 1.0),
    Intensity.HEAVY: (2, 2.0),
}


class Scheduler:
    """Adaptive scheduler preserving resource headroom.
    
    Rules:
    - Reserves headroom: cpu_headroom_ratio and mem_headroom_ratio
    - Never exceeds total resources minus headroom
    - Picks tasks from queue that fit in remaining capacity
    - Persistable + rehydratable
    """
    
    def __init__(
        self,
        profile: MachineProfile,
        *,
        cpu_headroom_ratio: float = 0.25,
        mem_headroom_ratio: float = 0.25,
    ) -> None:
        self._profile = profile
        self._cpu_headroom_ratio = cpu_headroom_ratio
        self._mem_headroom_ratio = mem_headroom_ratio
        self._queue: list[TaskEntry] = []
        self._running: dict[str, TaskEntry] = {}
    
    @property
    def max_cpu(self) -> int:
        return max(1, int(self._profile.cpu_count * (1 - self._cpu_headroom_ratio)))
    
    @property
    def max_memory_gb(self) -> float:
        return max(0.5, self._profile.available_memory_gb * (1 - self._mem_headroom_ratio))
    
    def enqueue(self, task_id: str, classification: IntensityClassification) -> TaskEntry:
        cpu, mem = INTENSITY_COSTS.get(classification.intensity, (1, 1.0))
        entry = TaskEntry(
            task_id=task_id,
            intensity=classification.intensity,
            cpu_cost=cpu,
            memory_cost_gb=mem,
        )
        self._queue.append(entry)
        return entry
    
    def current_cpu_usage(self) -> int:
        return sum(t.cpu_cost for t in self._running.values())
    
    def current_memory_usage(self) -> float:
        return sum(t.memory_cost_gb for t in self._running.values())
    
    def can_schedule(self, entry: TaskEntry) -> bool:
        """Check if this task fits in remaining capacity."""
        if self.current_cpu_usage() + entry.cpu_cost > self.max_cpu:
            return False
        if self.current_memory_usage() + entry.memory_cost_gb > self.max_memory_gb:
            return False
        return True
    
    def dispatch_next(self) -> TaskEntry | None:
        """Pick the next fittable task from queue and move to running.
        
        Preserves queue order for same-fit tasks.
        """
        for i, entry in enumerate(self._queue):
            if self.can_schedule(entry):
                self._queue.pop(i)
                entry.status = "running"
                entry.started_at = time.time()
                self._running[entry.task_id] = entry
                return entry
        return None
    
    def complete(self, task_id: str, success: bool = True) -> None:
        entry = self._running.pop(task_id, None)
        if entry:
            entry.status = "finished" if success else "failed"
            entry.finished_at = time.time()
    
    def pending_count(self) -> int:
        return len(self._queue)
    
    def running_count(self) -> int:
        return len(self._running)
    
    def to_dict(self) -> dict[str, Any]:
        return {
            "profile": self._profile.to_dict(),
            "cpu_headroom_ratio": self._cpu_headroom_ratio,
            "mem_headroom_ratio": self._mem_headroom_ratio,
            "queue": [_entry_to_dict(t) for t in self._queue],
            "running": {k: _entry_to_dict(v) for k, v in self._running.items()},
        }
    
    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Scheduler":
        sched = cls(
            profile=MachineProfile.from_dict(data["profile"]),
            cpu_headroom_ratio=data.get("cpu_headroom_ratio", 0.25),
            mem_headroom_ratio=data.get("mem_headroom_ratio", 0.25),
        )
        sched._queue = [_entry_from_dict(d) for d in data.get("queue", [])]
        sched._running = {k: _entry_from_dict(v) for k, v in data.get("running", {}).items()}
        return sched
    
    def save(self, path: str) -> None:
        tmp = path + ".tmp"
        with open(tmp, "w") as f:
            json.dump(self.to_dict(), f, indent=2)
        os.replace(tmp, path)
    
    @classmethod
    def load(cls, path: str) -> "Scheduler":
        with open(path, "r") as f:
            return cls.from_dict(json.load(f))


def _entry_to_dict(e: TaskEntry) -> dict[str, Any]:
    d = asdict(e)
    d["intensity"] = e.intensity.value
    return d


def _entry_from_dict(d: dict[str, Any]) -> TaskEntry:
    return TaskEntry(
        task_id=d["task_id"],
        intensity=Intensity(d["intensity"]),
        cpu_cost=d["cpu_cost"],
        memory_cost_gb=d["memory_cost_gb"],
        queued_at=d.get("queued_at", 0.0),
        started_at=d.get("started_at"),
        finished_at=d.get("finished_at"),
        status=d.get("status", "queued"),
    )

"""Phase 4: Harness-owned memory store and lessons.

Stores lessons learned from prior runs. Critical invariants:
- Harness-owned ONLY — no leakage from host conversation context
- Persistent across restarts
- Retrievable by task context
- Contradictory/stale lessons can be marked deprecated
- Injection into runs is explicit and auditable

Security boundary: this store must NOT accept arbitrary strings from
the host conversation context. All lessons come from recorded run outcomes.
"""

from __future__ import annotations

import json
import os
import time
import uuid
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Any


class LessonSource(str, Enum):
    """Where a lesson came from. Only these sources are valid."""
    RUN_OUTCOME = "run_outcome"     # derived from an actual run
    VALIDATION_FAILURE = "validation_failure"  # captured from a validation failure
    REVIEWER_FINDING = "reviewer_finding"      # reviewer explicitly flagged
    POST_MORTEM = "post_mortem"    # explicit postmortem entry


class LessonStatus(str, Enum):
    ACTIVE = "active"
    DEPRECATED = "deprecated"  # superseded or marked obsolete
    CONTRADICTORY = "contradictory"  # conflicts with another active lesson


@dataclass
class Lesson:
    lesson_id: str
    text: str
    source: LessonSource
    tags: list[str] = field(default_factory=list)
    source_run_id: str = ""  # required when source is RUN_OUTCOME etc.
    created_at: float = field(default_factory=time.time)
    status: LessonStatus = LessonStatus.ACTIVE
    superseded_by: str = ""
    
    def is_valid_for_injection(self) -> bool:
        return self.status == LessonStatus.ACTIVE


class MemoryStore:
    """Persistent, harness-owned lesson store.
    
    All lessons must have a valid LessonSource and (for run-derived sources)
    a source_run_id. Lessons without provenance are rejected.
    """
    
    def __init__(self, path: str | None = None) -> None:
        self._lessons: dict[str, Lesson] = {}
        self._path = path
        if path and os.path.exists(path):
            self._load()
    
    def add_lesson(
        self,
        text: str,
        source: LessonSource,
        source_run_id: str = "",
        tags: list[str] | None = None,
    ) -> Lesson:
        """Add a lesson with provenance validation.
        
        Security: rejects lessons without valid source provenance.
        """
        if not text.strip():
            raise ValueError("Lesson text cannot be empty")
        # Run-derived sources require a source_run_id
        if source in {LessonSource.RUN_OUTCOME, LessonSource.VALIDATION_FAILURE, LessonSource.REVIEWER_FINDING}:
            if not source_run_id:
                raise ValueError(
                    f"Lesson source {source.value} requires source_run_id"
                )
        
        lesson_id = f"lesson-{uuid.uuid4().hex[:12]}"
        lesson = Lesson(
            lesson_id=lesson_id,
            text=text,
            source=source,
            tags=list(tags or []),
            source_run_id=source_run_id,
        )
        self._lessons[lesson_id] = lesson
        if self._path:
            self._save()
        return lesson
    
    def get(self, lesson_id: str) -> Lesson | None:
        return self._lessons.get(lesson_id)
    
    def retrieve_by_tags(self, tags: list[str]) -> list[Lesson]:
        """Return active lessons matching any of the given tags."""
        tag_set = set(tags)
        return [
            l for l in self._lessons.values()
            if l.is_valid_for_injection() and (tag_set & set(l.tags))
        ]
    
    def retrieve_for_task(self, task_tags: list[str], limit: int = 5) -> list[Lesson]:
        """Return top-K active lessons for a task, sorted by recency."""
        matching = self.retrieve_by_tags(task_tags)
        matching.sort(key=lambda l: l.created_at, reverse=True)
        return matching[:limit]
    
    def deprecate(self, lesson_id: str, superseded_by: str = "") -> None:
        lesson = self._lessons.get(lesson_id)
        if lesson:
            lesson.status = LessonStatus.DEPRECATED
            lesson.superseded_by = superseded_by
            if self._path:
                self._save()
    
    def mark_contradictory(self, lesson_id: str) -> None:
        lesson = self._lessons.get(lesson_id)
        if lesson:
            lesson.status = LessonStatus.CONTRADICTORY
            if self._path:
                self._save()
    
    def count_active(self) -> int:
        return sum(1 for l in self._lessons.values() if l.is_valid_for_injection())
    
    def _save(self) -> None:
        data = {
            "lessons": {
                lid: {
                    "lesson_id": l.lesson_id,
                    "text": l.text,
                    "source": l.source.value,
                    "tags": list(l.tags),
                    "source_run_id": l.source_run_id,
                    "created_at": l.created_at,
                    "status": l.status.value,
                    "superseded_by": l.superseded_by,
                }
                for lid, l in self._lessons.items()
            }
        }
        tmp = self._path + ".tmp"
        with open(tmp, "w") as f:
            json.dump(data, f, indent=2)
        os.replace(tmp, self._path)
    
    def _load(self) -> None:
        with open(self._path, "r") as f:
            data = json.load(f)
        for lid, l_data in data.get("lessons", {}).items():
            self._lessons[lid] = Lesson(
                lesson_id=l_data["lesson_id"],
                text=l_data["text"],
                source=LessonSource(l_data["source"]),
                tags=list(l_data.get("tags", [])),
                source_run_id=l_data.get("source_run_id", ""),
                created_at=l_data.get("created_at", 0.0),
                status=LessonStatus(l_data.get("status", "active")),
                superseded_by=l_data.get("superseded_by", ""),
            )


@dataclass
class InjectionRecord:
    """Audit record of lesson injection into a run."""
    run_id: str
    lesson_ids: list[str]
    injected_at: float
    context: str


def inject_lessons_into_run(
    run_id: str,
    lessons: list[Lesson],
    context: str = "",
) -> InjectionRecord:
    """Injection is explicit and audited.
    
    Only lessons marked valid_for_injection are injected.
    """
    valid = [l for l in lessons if l.is_valid_for_injection()]
    return InjectionRecord(
        run_id=run_id,
        lesson_ids=[l.lesson_id for l in valid],
        injected_at=time.time(),
        context=context,
    )

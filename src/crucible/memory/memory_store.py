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
    """Where a lesson came from. Only these sources are valid.
    
    EVERY source requires a binding to a harness-owned artifact:
    - run_outcome → source_run_id
    - validation_failure → source_run_id
    - reviewer_finding → source_run_id
    - post_mortem → post_mortem_id (typed artifact, not free text)
    """
    RUN_OUTCOME = "run_outcome"
    VALIDATION_FAILURE = "validation_failure"
    REVIEWER_FINDING = "reviewer_finding"
    POST_MORTEM = "post_mortem"


class LessonStatus(str, Enum):
    ACTIVE = "active"
    DEPRECATED = "deprecated"  # superseded or marked obsolete
    CONTRADICTORY = "contradictory"  # conflicts with another active lesson


@dataclass
class PostMortemRecord:
    """A typed post-mortem artifact (NOT free text).
    
    Post-mortem records must be explicitly created via record_post_mortem()
    with a real triggering run/incident reference.
    """
    post_mortem_id: str
    title: str
    triggering_run_id: str  # the run that triggered the post-mortem
    summary: str
    created_at: float = field(default_factory=time.time)


@dataclass
class Lesson:
    lesson_id: str
    text: str
    source: LessonSource
    tags: list[str] = field(default_factory=list)
    source_run_id: str = ""
    post_mortem_id: str = ""
    created_at: float = field(default_factory=time.time)
    status: LessonStatus = LessonStatus.ACTIVE
    superseded_by: str = ""
    contradicts: list[str] = field(default_factory=list)
    
    def is_valid_for_injection(self) -> bool:
        return self.status == LessonStatus.ACTIVE


class HostMemoryLeakError(ValueError):
    """Raised when a lesson lacks valid harness-owned provenance."""
    pass


class MemoryStore:
    """Persistent, harness-owned lesson store.
    
    Security boundary (HARD):
    - Every lesson must reference a harness-owned record
    - Run-derived lessons → source_run_id must exist in known_run_ids set
    - Post-mortem lessons → post_mortem_id must exist in record store
    - Persisted state is re-validated on load
    """
    
    def __init__(
        self,
        path: str | None = None,
        *,
        known_run_ids: set[str] | None = None,
    ) -> None:
        self._lessons: dict[str, Lesson] = {}
        self._post_mortems: dict[str, PostMortemRecord] = {}
        # Set of run IDs the harness has actually seen — provenance verification source
        self._known_run_ids: set[str] = set(known_run_ids or [])
        self._injection_log: list[dict[str, Any]] = []
        self._path = path
        if path and os.path.exists(path):
            self._load()
    
    def register_run(self, run_id: str) -> None:
        """Register a run id as harness-owned. Only registered runs can be lesson sources."""
        self._known_run_ids.add(run_id)
        if self._path:
            self._save()
    
    def record_post_mortem(
        self,
        title: str,
        triggering_run_id: str,
        summary: str,
    ) -> PostMortemRecord:
        """Create a typed post-mortem record. The triggering run must be known."""
        if triggering_run_id not in self._known_run_ids:
            raise HostMemoryLeakError(
                f"Post-mortem triggering_run_id '{triggering_run_id}' not in known runs"
            )
        pm_id = f"pm-{uuid.uuid4().hex[:12]}"
        pm = PostMortemRecord(
            post_mortem_id=pm_id,
            title=title,
            triggering_run_id=triggering_run_id,
            summary=summary,
        )
        self._post_mortems[pm_id] = pm
        if self._path:
            self._save()
        return pm
    
    def add_lesson(
        self,
        text: str,
        source: LessonSource,
        source_run_id: str = "",
        post_mortem_id: str = "",
        tags: list[str] | None = None,
    ) -> Lesson:
        """Add a lesson with full provenance validation.
        
        Rejects lessons without valid harness-owned provenance.
        """
        if not text.strip():
            raise ValueError("Lesson text cannot be empty")
        
        # Provenance validation per source type
        if source in {LessonSource.RUN_OUTCOME, LessonSource.VALIDATION_FAILURE, LessonSource.REVIEWER_FINDING}:
            if not source_run_id:
                raise HostMemoryLeakError(
                    f"Lesson source {source.value} requires source_run_id"
                )
            if source_run_id not in self._known_run_ids:
                raise HostMemoryLeakError(
                    f"source_run_id '{source_run_id}' is not a registered harness run "
                    "(possible host memory leakage)"
                )
        elif source == LessonSource.POST_MORTEM:
            if not post_mortem_id:
                raise HostMemoryLeakError(
                    "Lesson source post_mortem requires post_mortem_id"
                )
            if post_mortem_id not in self._post_mortems:
                raise HostMemoryLeakError(
                    f"post_mortem_id '{post_mortem_id}' does not exist "
                    "(post-mortems must be created via record_post_mortem)"
                )
        
        lesson_id = f"lesson-{uuid.uuid4().hex[:12]}"
        lesson = Lesson(
            lesson_id=lesson_id,
            text=text,
            source=source,
            tags=list(tags or []),
            source_run_id=source_run_id,
            post_mortem_id=post_mortem_id,
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
    
    def mark_contradictory(self, lesson_id: str, conflicts_with: list[str] | None = None) -> None:
        """Mark a lesson contradictory and link to conflicting lesson(s).
        
        When two lessons conflict, both should be linked. Newer truth wins:
        retrieval prefers newer active lessons that aren't contradicted.
        """
        lesson = self._lessons.get(lesson_id)
        if lesson:
            lesson.status = LessonStatus.CONTRADICTORY
            if conflicts_with:
                lesson.contradicts = list(conflicts_with)
                # Also flag the other lessons so newer truth supersedes older
                for other_id in conflicts_with:
                    other = self._lessons.get(other_id)
                    if other:
                        # If the other is older and currently active, supersede it
                        if other.created_at < lesson.created_at:
                            other.status = LessonStatus.DEPRECATED
                            other.superseded_by = lesson_id
            if self._path:
                self._save()
    
    def count_active(self) -> int:
        return sum(1 for l in self._lessons.values() if l.is_valid_for_injection())
    
    def _save(self) -> None:
        data = {
            "known_run_ids": sorted(self._known_run_ids),
            "post_mortems": {
                pid: {
                    "post_mortem_id": p.post_mortem_id,
                    "title": p.title,
                    "triggering_run_id": p.triggering_run_id,
                    "summary": p.summary,
                    "created_at": p.created_at,
                }
                for pid, p in self._post_mortems.items()
            },
            "lessons": {
                lid: {
                    "lesson_id": l.lesson_id,
                    "text": l.text,
                    "source": l.source.value,
                    "tags": list(l.tags),
                    "source_run_id": l.source_run_id,
                    "post_mortem_id": l.post_mortem_id,
                    "created_at": l.created_at,
                    "status": l.status.value,
                    "superseded_by": l.superseded_by,
                    "contradicts": list(l.contradicts),
                }
                for lid, l in self._lessons.items()
            },
            "injection_log": list(self._injection_log),
        }
        tmp = self._path + ".tmp"
        with open(tmp, "w") as f:
            json.dump(data, f, indent=2)
        os.replace(tmp, self._path)
    
    def _load(self) -> None:
        with open(self._path, "r") as f:
            data = json.load(f)
        
        self._known_run_ids = set(data.get("known_run_ids", []))
        
        # Load post-mortems WITH triggering_run_id validation
        for pid, p_data in data.get("post_mortems", {}).items():
            triggering_run_id = p_data["triggering_run_id"]
            if triggering_run_id not in self._known_run_ids:
                raise HostMemoryLeakError(
                    f"Persisted post-mortem {pid} has invalid triggering_run_id "
                    f"'{triggering_run_id}' (possible tamper)"
                )
            self._post_mortems[pid] = PostMortemRecord(
                post_mortem_id=p_data["post_mortem_id"],
                title=p_data["title"],
                triggering_run_id=triggering_run_id,
                summary=p_data["summary"],
                created_at=p_data.get("created_at", 0.0),
            )
        
        # Load lessons WITH provenance re-validation
        for lid, l_data in data.get("lessons", {}).items():
            source = LessonSource(l_data["source"])
            source_run_id = l_data.get("source_run_id", "")
            post_mortem_id = l_data.get("post_mortem_id", "")
            
            # Re-validate provenance on load
            if source in {LessonSource.RUN_OUTCOME, LessonSource.VALIDATION_FAILURE, LessonSource.REVIEWER_FINDING}:
                if not source_run_id or source_run_id not in self._known_run_ids:
                    raise HostMemoryLeakError(
                        f"Persisted lesson {lid} has invalid source_run_id "
                        f"(possible tamper or host leakage)"
                    )
            elif source == LessonSource.POST_MORTEM:
                if not post_mortem_id or post_mortem_id not in self._post_mortems:
                    raise HostMemoryLeakError(
                        f"Persisted lesson {lid} has invalid post_mortem_id"
                    )
            
            self._lessons[lid] = Lesson(
                lesson_id=l_data["lesson_id"],
                text=l_data["text"],
                source=source,
                tags=list(l_data.get("tags", [])),
                source_run_id=source_run_id,
                post_mortem_id=post_mortem_id,
                created_at=l_data.get("created_at", 0.0),
                status=LessonStatus(l_data.get("status", "active")),
                superseded_by=l_data.get("superseded_by", ""),
                contradicts=list(l_data.get("contradicts", [])),
            )
        
        self._injection_log = list(data.get("injection_log", []))


@dataclass
class InjectionRecord:
    """Audit record of lesson injection into a run."""
    run_id: str
    lesson_ids: list[str]
    injected_at: float
    context: str
    
    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "lesson_ids": list(self.lesson_ids),
            "injected_at": self.injected_at,
            "context": self.context,
        }


def inject_lessons_into_run(
    run_id: str,
    lessons: list[Lesson],
    context: str = "",
    store: MemoryStore | None = None,
) -> InjectionRecord:
    """Injection is explicit and durably audited (when store provided).
    
    Only lessons marked valid_for_injection are injected.
    If store is provided, the audit record is persisted alongside the store.
    """
    valid = [l for l in lessons if l.is_valid_for_injection()]
    record = InjectionRecord(
        run_id=run_id,
        lesson_ids=[l.lesson_id for l in valid],
        injected_at=time.time(),
        context=context,
    )
    if store is not None:
        store._injection_log.append(record.to_dict())
        if store._path:
            store._save()
    return record

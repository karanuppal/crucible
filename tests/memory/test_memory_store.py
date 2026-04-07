"""Phase 4 tests: harness-owned memory store."""

import pytest

from agentic_harness.memory.memory_store import (
    MemoryStore, Lesson, LessonSource, LessonStatus,
    inject_lessons_into_run,
)


class TestLessonProvenance:
    def test_run_outcome_requires_run_id(self, tmp_path):
        store = MemoryStore(str(tmp_path / "mem.json"))
        
        with pytest.raises(ValueError, match="source_run_id"):
            store.add_lesson(
                text="Some lesson",
                source=LessonSource.RUN_OUTCOME,
                # missing source_run_id
            )
    
    def test_validation_failure_requires_run_id(self, tmp_path):
        store = MemoryStore(str(tmp_path / "mem.json"))
        with pytest.raises(ValueError, match="source_run_id"):
            store.add_lesson(
                text="Validation lesson",
                source=LessonSource.VALIDATION_FAILURE,
            )
    
    def test_post_mortem_no_run_id_needed(self, tmp_path):
        store = MemoryStore(str(tmp_path / "mem.json"))
        # Post-mortem doesn't require a run_id
        lesson = store.add_lesson(
            text="Retrospective learning",
            source=LessonSource.POST_MORTEM,
        )
        assert lesson.lesson_id.startswith("lesson-")
    
    def test_empty_lesson_rejected(self, tmp_path):
        store = MemoryStore(str(tmp_path / "mem.json"))
        with pytest.raises(ValueError, match="empty"):
            store.add_lesson(text="", source=LessonSource.POST_MORTEM)


class TestRetrieval:
    def test_retrieve_by_tags(self, tmp_path):
        store = MemoryStore(str(tmp_path / "mem.json"))
        l1 = store.add_lesson("python tip", LessonSource.POST_MORTEM, tags=["python"])
        l2 = store.add_lesson("rust tip", LessonSource.POST_MORTEM, tags=["rust"])
        
        results = store.retrieve_by_tags(["python"])
        assert len(results) == 1
        assert results[0].lesson_id == l1.lesson_id
    
    def test_retrieve_excludes_deprecated(self, tmp_path):
        store = MemoryStore(str(tmp_path / "mem.json"))
        l1 = store.add_lesson("old tip", LessonSource.POST_MORTEM, tags=["python"])
        store.deprecate(l1.lesson_id)
        
        results = store.retrieve_by_tags(["python"])
        assert len(results) == 0
    
    def test_retrieve_excludes_contradictory(self, tmp_path):
        store = MemoryStore(str(tmp_path / "mem.json"))
        l1 = store.add_lesson("tip", LessonSource.POST_MORTEM, tags=["x"])
        store.mark_contradictory(l1.lesson_id)
        
        assert len(store.retrieve_by_tags(["x"])) == 0
    
    def test_retrieve_limited(self, tmp_path):
        store = MemoryStore(str(tmp_path / "mem.json"))
        for i in range(10):
            store.add_lesson(f"tip {i}", LessonSource.POST_MORTEM, tags=["a"])
        
        results = store.retrieve_for_task(["a"], limit=3)
        assert len(results) == 3


class TestPersistenceAndRestart:
    def test_lessons_survive_restart(self, tmp_path):
        path = str(tmp_path / "mem.json")
        store1 = MemoryStore(path)
        lesson = store1.add_lesson(
            text="Critical lesson",
            source=LessonSource.RUN_OUTCOME,
            source_run_id="run-123",
            tags=["auth"],
        )
        
        # Restart
        store2 = MemoryStore(path)
        loaded = store2.get(lesson.lesson_id)
        assert loaded is not None
        assert loaded.text == "Critical lesson"
        assert loaded.source_run_id == "run-123"
    
    def test_deprecation_survives_restart(self, tmp_path):
        path = str(tmp_path / "mem.json")
        s1 = MemoryStore(path)
        l = s1.add_lesson("old", LessonSource.POST_MORTEM, tags=["x"])
        s1.deprecate(l.lesson_id)
        
        s2 = MemoryStore(path)
        assert s2.get(l.lesson_id).status == LessonStatus.DEPRECATED


class TestInjection:
    def test_inject_only_active_lessons(self, tmp_path):
        store = MemoryStore(str(tmp_path / "mem.json"))
        l1 = store.add_lesson("active", LessonSource.POST_MORTEM, tags=["a"])
        l2 = store.add_lesson("deprecated", LessonSource.POST_MORTEM, tags=["a"])
        store.deprecate(l2.lesson_id)
        
        lessons = [store.get(l1.lesson_id), store.get(l2.lesson_id)]
        record = inject_lessons_into_run("run-1", lessons, context="retry path")
        
        assert l1.lesson_id in record.lesson_ids
        assert l2.lesson_id not in record.lesson_ids
    
    def test_injection_record_audited(self, tmp_path):
        store = MemoryStore(str(tmp_path / "mem.json"))
        l = store.add_lesson("x", LessonSource.POST_MORTEM, tags=["a"])
        
        record = inject_lessons_into_run("run-1", [l], context="initial setup")
        assert record.run_id == "run-1"
        assert record.context == "initial setup"
        assert record.injected_at > 0

"""Phase 4 tests: memory store with strict provenance."""

import pytest
import time

from agentic_harness.memory.memory_store import (
    MemoryStore, LessonSource, LessonStatus, HostMemoryLeakError,
    inject_lessons_into_run,
)


def _store_with_runs(tmp_path, runs=None):
    store = MemoryStore(str(tmp_path / "mem.json"), known_run_ids=set(runs or []))
    for r in (runs or []):
        store.register_run(r)
    return store


class TestLessonProvenance:
    def test_run_outcome_requires_registered_run(self, tmp_path):
        store = _store_with_runs(tmp_path)
        with pytest.raises(HostMemoryLeakError):
            store.add_lesson("x", LessonSource.RUN_OUTCOME, source_run_id="run-unknown")
    
    def test_registered_run_accepted(self, tmp_path):
        store = _store_with_runs(tmp_path, ["run-1"])
        lesson = store.add_lesson("tip", LessonSource.RUN_OUTCOME, source_run_id="run-1")
        assert lesson.source_run_id == "run-1"
    
    def test_post_mortem_requires_record(self, tmp_path):
        store = _store_with_runs(tmp_path, ["r1"])
        with pytest.raises(HostMemoryLeakError):
            store.add_lesson("x", LessonSource.POST_MORTEM, post_mortem_id="pm-none")
    
    def test_post_mortem_flow(self, tmp_path):
        store = _store_with_runs(tmp_path, ["trigger-run"])
        pm = store.record_post_mortem(title="Outage", triggering_run_id="trigger-run", summary="Fix")
        lesson = store.add_lesson("Use pool", LessonSource.POST_MORTEM, post_mortem_id=pm.post_mortem_id, tags=["db"])
        assert lesson.post_mortem_id == pm.post_mortem_id


class TestRetrieval:
    def test_retrieve_active(self, tmp_path):
        store = _store_with_runs(tmp_path, ["r1"])
        store.add_lesson("active tip", LessonSource.RUN_OUTCOME, source_run_id="r1", tags=["x"])
        results = store.retrieve_by_tags(["x"])
        assert len(results) == 1
    
    def test_deprecated_excluded(self, tmp_path):
        store = _store_with_runs(tmp_path, ["r1"])
        l = store.add_lesson("old", LessonSource.RUN_OUTCOME, source_run_id="r1", tags=["x"])
        store.deprecate(l.lesson_id)
        assert len(store.retrieve_by_tags(["x"])) == 0
    
    def test_contradictory_excluded(self, tmp_path):
        store = _store_with_runs(tmp_path, ["r1", "r2"])
        l1 = store.add_lesson("old", LessonSource.RUN_OUTCOME, source_run_id="r1", tags=["x"])
        time.sleep(0.01)
        l2 = store.add_lesson("new", LessonSource.RUN_OUTCOME, source_run_id="r2", tags=["x"])
        store.mark_contradictory(l2.lesson_id, conflicts_with=[l1.lesson_id])
        assert len(store.retrieve_by_tags(["x"])) == 0


class TestPersistence:
    def test_reload_preserves_lessons(self, tmp_path):
        path = str(tmp_path / "mem.json")
        s1 = _store_with_runs(tmp_path, ["r1"])
        s1.add_lesson("tip", LessonSource.RUN_OUTCOME, source_run_id="r1", tags=["a"])
        
        s2 = _store_with_runs(tmp_path, ["r1"])
        assert s2.count_active() == 1
    
    def test_tampered_post_mortem_rejected(self, tmp_path):
        """Tampered post-mortem triggering_run_id must be rejected on load."""
        path = str(tmp_path / "mem.json")
        s1 = _store_with_runs(tmp_path, ["real-run"])
        pm = s1.record_post_mortem(title="x", triggering_run_id="real-run", summary="x")
        s1.add_lesson("tip", LessonSource.POST_MORTEM, post_mortem_id=pm.post_mortem_id, tags=["x"])
        
        import json
        with open(path) as f:
            data = json.load(f)
        # Tamper: change the post-mortem's triggering_run_id
        data["post_mortems"][pm.post_mortem_id]["triggering_run_id"] = "fake-run"
        with open(path, "w") as f:
            json.dump(data, f)
        
        with pytest.raises(HostMemoryLeakError):
            _store_with_runs(tmp_path, ["real-run"])
    
    def test_tampered_provenance_rejected(self, tmp_path):
        path = str(tmp_path / "mem.json")
        s1 = _store_with_runs(tmp_path, ["r1"])
        s1.add_lesson("tip", LessonSource.RUN_OUTCOME, source_run_id="r1", tags=["a"])
        
        # Tamper: forge a lesson with unknown run
        import json
        with open(path) as f:
            data = json.load(f)
        data["lessons"][" forged"] = {
            "lesson_id": "forged",
            "text": "forged",
            "source": "run_outcome",
            "tags": [],
            "source_run_id": "unknown-run",
            "post_mortem_id": "",
            "created_at": 0.0,
            "status": "active",
            "superseded_by": "",
            "contradicts": [],
        }
        with open(path, "w") as f:
            json.dump(data, f)
        
        with pytest.raises(HostMemoryLeakError):
            _store_with_runs(tmp_path, ["r1"])


class TestInjection:
    def test_only_active_injected(self, tmp_path):
        store = _store_with_runs(tmp_path, ["r1"])
        l1 = store.add_lesson("good", LessonSource.RUN_OUTCOME, source_run_id="r1", tags=["a"])
        l2 = store.add_lesson("bad", LessonSource.RUN_OUTCOME, source_run_id="r1", tags=["a"])
        store.deprecate(l2.lesson_id)
        
        record = inject_lessons_into_run("run-target", [l1, l2], store=store)
        assert l1.lesson_id in record.lesson_ids
        assert l2.lesson_id not in record.lesson_ids
    
    def test_injection_persisted(self, tmp_path):
        path = str(tmp_path / "mem.json")
        store = _store_with_runs(tmp_path, ["r1"])
        l = store.add_lesson("tip", LessonSource.RUN_OUTCOME, source_run_id="r1", tags=["a"])
        inject_lessons_into_run("run-target", [l], context="retry", store=store)
        
        store2 = _store_with_runs(tmp_path, ["r1"])
        assert len(store2._injection_log) == 1

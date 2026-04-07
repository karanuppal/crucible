"""Phase 8 tests: durable run store."""

import json
import os
import pytest

from crucible.runtime.run_store import (
    RunStore, RunManifest, RunEvent, TaskAttemptRecord, RunSummary, CostSummary,
    create_run_store, load_run_store, new_run_id,
)


def _plan():
    return {
        "spec": "test spec",
        "project_id": "p1",
        "build_id": "b1",
        "tasks": [
            {
                "task_id": "t1",
                "description": "implement foo with tests",
                "criteria": [{"criterion_id": "c1", "criterion_class": "must_pass",
                              "triple": {"build_target": "src/foo.py",
                                         "verification_command": "pytest tests/test_foo.py",
                                         "expected_output": "PASSED"}}],
                "role": "builder", "intensity_hint": "S",
            }
        ],
    }


class TestCreateAndLoad:
    def test_create_persists_manifest_and_tasks(self, tmp_path):
        store, manifest = create_run_store(
            run_id=None,
            project_id="p1",
            build_id="b1",
            spec_text="test spec",
            task_plan=_plan(),
            runs_root=str(tmp_path / "runs"),
        )
        assert os.path.isfile(store.manifest_path)
        assert os.path.isfile(store.tasks_path)
        assert os.path.isfile(store.events_path)  # run_started event
        
        loaded = store.read_manifest()
        assert loaded.run_id == manifest.run_id
        assert loaded.project_id == "p1"
        assert loaded.current_status == "running"
    
    def test_load_existing_run(self, tmp_path):
        store, manifest = create_run_store(
            run_id=None, project_id="p1", build_id="b1",
            spec_text="x", task_plan=_plan(),
            runs_root=str(tmp_path / "runs"),
        )
        
        loaded = load_run_store(manifest.run_id, runs_root=str(tmp_path / "runs"))
        assert loaded is not None
        assert loaded.read_manifest().run_id == manifest.run_id
    
    def test_load_unknown_returns_none(self, tmp_path):
        loaded = load_run_store("nonexistent", runs_root=str(tmp_path / "runs"))
        assert loaded is None


class TestEvents:
    def test_append_and_read(self, tmp_path):
        store, manifest = create_run_store(
            run_id=None, project_id="p1", build_id="b1",
            spec_text="x", task_plan=_plan(),
            runs_root=str(tmp_path / "runs"),
        )
        
        store.append_event("task_dispatched", task_id="t1")
        store.append_event("task_completed", task_id="t1")
        
        events = store.read_events()
        # run_started + 2 = 3
        assert len(events) == 3
        assert events[1].type == "task_dispatched"
        assert events[2].type == "task_completed"
    
    def test_events_replay_from_zero(self, tmp_path):
        store, _ = create_run_store(
            run_id=None, project_id="p1", build_id="b1",
            spec_text="x", task_plan=_plan(),
            runs_root=str(tmp_path / "runs"),
        )
        store.append_event("a")
        store.append_event("b")
        
        events = store.read_events(from_event_id="0")
        assert len(events) >= 3


class TestAttempts:
    def test_write_and_read_attempt(self, tmp_path):
        store, _ = create_run_store(
            run_id=None, project_id="p1", build_id="b1",
            spec_text="x", task_plan=_plan(),
            runs_root=str(tmp_path / "runs"),
        )
        
        attempt = TaskAttemptRecord(
            attempt_id="t1-attempt-0",
            task_id="t1",
            attempt_index=0,
            backend_id="test",
            status="running",
            workspace_ref="/tmp/wt-1",
        )
        store.write_attempt(attempt)
        
        loaded = store.read_attempt("t1-attempt-0")
        assert loaded is not None
        assert loaded.task_id == "t1"
        assert loaded.workspace_ref == "/tmp/wt-1"
    
    def test_list_attempts(self, tmp_path):
        store, _ = create_run_store(
            run_id=None, project_id="p1", build_id="b1",
            spec_text="x", task_plan=_plan(),
            runs_root=str(tmp_path / "runs"),
        )
        for i in range(3):
            store.write_attempt(TaskAttemptRecord(
                attempt_id=f"t{i}-attempt-0",
                task_id=f"t{i}",
                attempt_index=0,
                backend_id="test",
                status="complete",
            ))
        assert len(store.list_attempts()) == 3
    
    def test_attempts_for_task(self, tmp_path):
        store, _ = create_run_store(
            run_id=None, project_id="p1", build_id="b1",
            spec_text="x", task_plan=_plan(),
            runs_root=str(tmp_path / "runs"),
        )
        store.write_attempt(TaskAttemptRecord(
            attempt_id="t1-attempt-0", task_id="t1", attempt_index=0,
            backend_id="b", status="failed",
        ))
        store.write_attempt(TaskAttemptRecord(
            attempt_id="t1-attempt-1", task_id="t1", attempt_index=1,
            backend_id="b", status="complete", winning_attempt=True,
        ))
        
        attempts = store.attempts_for_task("t1")
        assert len(attempts) == 2
        winning = [a for a in attempts if a.winning_attempt]
        assert len(winning) == 1


class TestReconciliation:
    def test_in_flight_attempt_marked_after_restart(self, tmp_path):
        store, _ = create_run_store(
            run_id=None, project_id="p1", build_id="b1",
            spec_text="x", task_plan=_plan(),
            runs_root=str(tmp_path / "runs"),
        )
        # Simulate crash mid-run: attempt is still RUNNING
        store.write_attempt(TaskAttemptRecord(
            attempt_id="t1-attempt-0", task_id="t1", attempt_index=0,
            backend_id="b", status="running",
        ))
        
        flagged = store.reconcile_in_flight_attempts()
        assert len(flagged) == 1
        assert flagged[0].needs_reconciliation
        assert "post-restart" in flagged[0].blockers[0]
        
        # Re-read to confirm persisted
        loaded = store.read_attempt("t1-attempt-0")
        assert loaded.needs_reconciliation
    
    def test_terminal_attempts_not_flagged(self, tmp_path):
        store, _ = create_run_store(
            run_id=None, project_id="p1", build_id="b1",
            spec_text="x", task_plan=_plan(),
            runs_root=str(tmp_path / "runs"),
        )
        store.write_attempt(TaskAttemptRecord(
            attempt_id="t1-attempt-0", task_id="t1", attempt_index=0,
            backend_id="b", status="complete",
        ))
        
        flagged = store.reconcile_in_flight_attempts()
        assert flagged == []


class TestResult:
    def test_write_result_marks_terminal(self, tmp_path):
        store, manifest = create_run_store(
            run_id=None, project_id="p1", build_id="b1",
            spec_text="x", task_plan=_plan(),
            runs_root=str(tmp_path / "runs"),
        )
        assert not store.is_terminal()
        
        summary = RunSummary(
            run_id=manifest.run_id,
            terminal_status="complete",
            completed_tasks=["t1"],
            total_runtime_seconds=1.5,
        )
        store.write_result(summary)
        
        assert store.is_terminal()
        result = store.read_result()
        assert result["terminal_status"] == "complete"
        assert result["completed_tasks"] == ["t1"]


class TestAdapterState:
    def test_write_read_adapter_state(self, tmp_path):
        store, _ = create_run_store(
            run_id=None, project_id="p1", build_id="b1",
            spec_text="x", task_plan=_plan(),
            runs_root=str(tmp_path / "runs"),
        )
        
        state = {"handle_id": "h1", "status": "running"}
        store.write_adapter_state("h1", state)
        
        loaded = store.read_adapter_state("h1")
        assert loaded["status"] == "running"
        assert "h1" in store.list_adapter_handles()
    
    def test_read_unknown_handle(self, tmp_path):
        store, _ = create_run_store(
            run_id=None, project_id="p1", build_id="b1",
            spec_text="x", task_plan=_plan(),
            runs_root=str(tmp_path / "runs"),
        )
        assert store.read_adapter_state("nonexistent") is None

from crucible.runtime.resume_handler import ResumeHandler
from crucible.runtime.run_store import TaskAttemptRecord, create_run_store


def test_resume_handler_reconstructs_semantic_state(tmp_path):
    store, manifest = create_run_store(
        run_id="run-1",
        project_id="proj",
        build_id="b1",
        spec_text="spec",
        task_plan={"project_id": "proj", "build_id": "b1", "tasks": []},
        runs_root=str(tmp_path),
        workspace_root=str(tmp_path / "ws"),
    )
    store.update_manifest_status("execute", "running")
    store.write_attempt(TaskAttemptRecord(
        attempt_id="task-1-attempt-0",
        task_id="task-1",
        attempt_index=0,
        backend_id="local",
        status="running",
    ))
    snapshot = ResumeHandler().reconstruct(store)
    assert snapshot.run_id == manifest.run_id
    assert snapshot.semantic_state == "repairing"
    assert snapshot.active_tasks == ["task-1"]
    assert snapshot.reconciled_attempts == ["task-1-attempt-0"]

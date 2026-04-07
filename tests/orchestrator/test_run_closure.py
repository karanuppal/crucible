from crucible.orchestrator.run_closure import RunClosure


def test_run_closure_complete_when_all_tasks_complete():
    result = RunClosure().evaluate([
        {"task_id": "t1", "status": "complete"},
        {"task_id": "t2", "status": "complete"},
    ])
    assert result.terminal_status == "complete"
    assert result.completed_tasks == ["t1", "t2"]


def test_run_closure_blocks_on_awaiting_user():
    result = RunClosure().evaluate([
        {"task_id": "t1", "status": "awaiting_user"},
    ])
    assert result.terminal_status == "blocked"
    assert "awaiting_user:t1" in result.blockers


def test_run_closure_partial_when_task_still_active():
    result = RunClosure().evaluate([
        {"task_id": "t1", "status": "building"},
        {"task_id": "t2", "status": "complete"},
    ])
    assert result.terminal_status == "partial"
    assert result.partial_tasks == ["t1"]


def test_run_closure_requires_integration_before_completion():
    result = RunClosure().evaluate(
        [{"task_id": "t1", "status": "complete"}],
        integration_required=True,
        integration_complete=False,
    )
    assert result.terminal_status == "partial"
    assert result.blockers == ["integration_incomplete"]


def test_run_closure_requires_post_validation_after_integration():
    result = RunClosure().evaluate(
        [{"task_id": "t1", "status": "complete"}],
        integration_required=True,
        integration_complete=True,
        post_validation_required=True,
        post_validation_passed=False,
    )
    assert result.terminal_status == "failed"
    assert result.blockers == ["post_validation_failed"]


def test_run_closure_rejects_post_validation_without_integration_contract():
    result = RunClosure().evaluate(
        [{"task_id": "t1", "status": "complete"}],
        integration_required=False,
        post_validation_required=True,
        post_validation_passed=True,
    )
    assert result.terminal_status == "failed"
    assert result.blockers == ["post_validation_requires_integration"]

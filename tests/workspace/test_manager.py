from crucible.state.workspace_record import WorkspaceLineageType, WorkspaceRecord, WorkspaceCleanupStatus
from crucible.workspace.manager import WorkspaceManager


def test_workspace_manager_create_and_cleanup(tmp_path):
    manager = WorkspaceManager(tmp_path)
    record = WorkspaceRecord(task_id="task-1", workspace_id="ws-1", lineage_type=WorkspaceLineageType.FRESH)
    created = manager.create(record)
    assert created.path is not None
    assert created.cleanup_status == WorkspaceCleanupStatus.ACTIVE
    cleaned = manager.cleanup(created)
    assert cleaned.cleanup_status == WorkspaceCleanupStatus.CLEANED


def test_workspace_manager_preserve(tmp_path):
    manager = WorkspaceManager(tmp_path)
    record = WorkspaceRecord(task_id="task-1", workspace_id="ws-2", lineage_type=WorkspaceLineageType.FRESH)
    created = manager.create(record)
    preserved = manager.cleanup(created, preserve=True)
    assert preserved.cleanup_status == WorkspaceCleanupStatus.PRESERVED

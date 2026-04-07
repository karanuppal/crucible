"""Workspace manager for Crucible v5.4."""

from __future__ import annotations

from pathlib import Path

from crucible.state.workspace_record import WorkspaceCleanupStatus, WorkspaceRecord


class WorkspaceManager:
    def __init__(self, root: str | Path):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def create(self, record: WorkspaceRecord) -> WorkspaceRecord:
        workspace_id = record.workspace_id or f"ws-{record.task_id or 'task'}-{len(list(self.root.iterdir())) + 1}"
        path = self.root / workspace_id
        path.mkdir(parents=True, exist_ok=True)
        record.workspace_id = workspace_id
        record.path = str(path)
        record.cleanup_status = WorkspaceCleanupStatus.ACTIVE
        return record

    def cleanup(self, record: WorkspaceRecord, *, preserve: bool = False) -> WorkspaceRecord:
        if not record.path:
            return record
        path = Path(record.path)
        if preserve:
            record.cleanup_status = WorkspaceCleanupStatus.PRESERVED
            return record
        if path.exists():
            for child in sorted(path.rglob('*'), reverse=True):
                if child.is_file() or child.is_symlink():
                    child.unlink()
                elif child.is_dir():
                    child.rmdir()
            path.rmdir()
        record.cleanup_status = WorkspaceCleanupStatus.CLEANED
        return record

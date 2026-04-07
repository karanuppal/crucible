"""Tests for workspace record."""

import pytest

from crucible.state.workspace_record import (
    WorkspaceBasisType,
    WorkspaceCleanupStatus,
    WorkspaceLineageType,
    WorkspaceRecord,
)


class TestWorkspaceRecord:
    def test_fresh_workspace(self):
        record = WorkspaceRecord(lineage_type=WorkspaceLineageType.FRESH)
        assert record.lineage_type == WorkspaceLineageType.FRESH
        assert record.basis_attempt_id is None
        assert record.is_inherited() is False
        assert record.is_salvage() is False
        assert record.basis_type == WorkspaceBasisType.FRESH
        assert record.allows_modification() is True

    def test_repair_basis_requires_attempt_id(self):
        record = WorkspaceRecord(
            lineage_type=WorkspaceLineageType.REPAIR_BASIS,
            basis_attempt_id="attempt-123",
        )
        assert record.basis_attempt_id == "attempt-123"
        assert record.is_inherited() is True
        assert record.source_attempt_ids == ["attempt-123"]
        assert record.basis_type == WorkspaceBasisType.INHERITED

    def test_salvage_inherit_requires_attempt_id(self):
        record = WorkspaceRecord(
            lineage_type=WorkspaceLineageType.SALVAGE_INHERIT,
            basis_attempt_id="attempt-456",
            partial_artifacts=["output.log", "diff.patch"],
        )
        assert record.is_inherited() is True
        assert record.is_salvage() is True
        assert record.allows_modification() is True

    def test_salvage_replay(self):
        record = WorkspaceRecord(
            lineage_type=WorkspaceLineageType.SALVAGE_REPLAY,
            basis_attempt_id="attempt-789",
            partial_artifacts=["partial.py"],
        )
        assert record.is_salvage() is True
        assert record.basis_type == WorkspaceBasisType.REPLAYED

    def test_partial_consume_readonly(self):
        record = WorkspaceRecord(
            lineage_type=WorkspaceLineageType.PARTIAL_CONSUME,
            basis_attempt_id="attempt-000",
            partial_artifacts=["readme.txt"],
        )
        assert record.is_salvage() is True
        assert record.allows_modification() is False

    def test_repair_basis_without_id_raises(self):
        with pytest.raises(ValueError, match="requires basis_attempt_id"):
            WorkspaceRecord(lineage_type=WorkspaceLineageType.REPAIR_BASIS)

    def test_salvage_inherit_without_id_raises(self):
        with pytest.raises(ValueError, match="requires basis_attempt_id"):
            WorkspaceRecord(
                lineage_type=WorkspaceLineageType.SALVAGE_INHERIT,
                partial_artifacts=["test.log"],
            )

    def test_partial_artifacts_without_id_raises(self):
        with pytest.raises(ValueError, match="requires basis_attempt_id"):
            WorkspaceRecord(
                lineage_type=WorkspaceLineageType.FRESH,
                partial_artifacts=["test.log"],
            )

    def test_fresh_workspace_cannot_declare_basis_attempt(self):
        with pytest.raises(ValueError, match="fresh workspaces"):
            WorkspaceRecord(
                lineage_type=WorkspaceLineageType.FRESH,
                basis_attempt_id="attempt-1",
            )

    def test_to_dict_contains_spec_fields(self):
        record = WorkspaceRecord(
            workspace_id="ws-1",
            task_id="task-1",
            lineage_type=WorkspaceLineageType.SALVAGE_REPLAY,
            basis_attempt_id="attempt-2",
            path="/tmp/ws-1",
            cleanup_status=WorkspaceCleanupStatus.ACTIVE,
        )
        data = record.to_dict()
        assert data["workspace_id"] == "ws-1"
        assert data["task_id"] == "task-1"
        assert data["basis_type"] == "replayed"
        assert data["cleanup_status"] == "active"
        assert data["source_attempt_ids"] == ["attempt-2"]

    def test_all_lineage_types_covered(self):
        types = list(WorkspaceLineageType)
        assert len(types) == 5
        assert WorkspaceLineageType.FRESH in types
        assert WorkspaceLineageType.REPAIR_BASIS in types
        assert WorkspaceLineageType.SALVAGE_INHERIT in types
        assert WorkspaceLineageType.SALVAGE_REPLAY in types
        assert WorkspaceLineageType.PARTIAL_CONSUME in types

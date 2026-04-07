"""Workspace lineage record for Crucible v5.4.

Every attempt must know whether it starts fresh, inherits from a previous
attempt, or consumes partial outputs through a controlled salvage path.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import Any


class WorkspaceLineageType(str, Enum):
    """Distinguishes how this attempt's workspace was created."""

    FRESH = "fresh"
    REPAIR_BASIS = "repair_basis"
    SALVAGE_INHERIT = "salvage_inherit"
    SALVAGE_REPLAY = "salvage_replay"
    PARTIAL_CONSUME = "partial_consume"


class WorkspaceBasisType(str, Enum):
    """Spec-facing normalized basis type."""

    FRESH = "fresh"
    INHERITED = "inherited"
    REPLAYED = "replayed"
    INTEGRATED = "integrated"


class WorkspaceCleanupStatus(str, Enum):
    PENDING = "pending"
    ACTIVE = "active"
    CLEANED = "cleaned"
    PRESERVED = "preserved"
    FAILED = "failed"


_LINEAGE_TO_BASIS: dict[WorkspaceLineageType, WorkspaceBasisType] = {
    WorkspaceLineageType.FRESH: WorkspaceBasisType.FRESH,
    WorkspaceLineageType.REPAIR_BASIS: WorkspaceBasisType.INHERITED,
    WorkspaceLineageType.SALVAGE_INHERIT: WorkspaceBasisType.INHERITED,
    WorkspaceLineageType.SALVAGE_REPLAY: WorkspaceBasisType.REPLAYED,
    WorkspaceLineageType.PARTIAL_CONSUME: WorkspaceBasisType.REPLAYED,
}


@dataclass
class WorkspaceRecord:
    """Records the lineage and origin of an attempt workspace.

    The original Phase 1 contract only stored lineage_type + basis_attempt_id.
    v5.4 needs a richer first-class workspace object, but we keep the old field
    names so existing tests and callers remain valid.
    """

    lineage_type: WorkspaceLineageType
    basis_attempt_id: str | None = None
    basis_workspace_path: str | None = None
    partial_artifacts: list[str] | None = None

    workspace_id: str | None = None
    task_id: str | None = None
    basis_type: WorkspaceBasisType | None = None
    basis_ref: str | None = None
    path: str | None = None
    source_attempt_ids: list[str] = field(default_factory=list)
    mutable: bool | None = None
    created_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    cleanup_status: WorkspaceCleanupStatus = WorkspaceCleanupStatus.PENDING
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.lineage_type in (
            WorkspaceLineageType.REPAIR_BASIS,
            WorkspaceLineageType.SALVAGE_INHERIT,
        ) and not self.basis_attempt_id:
            raise ValueError(f"{self.lineage_type.value} requires basis_attempt_id")

        if self.partial_artifacts and not self.basis_attempt_id:
            raise ValueError("partial_artifacts requires basis_attempt_id")

        if self.basis_type is None:
            self.basis_type = _LINEAGE_TO_BASIS[self.lineage_type]
        if self.basis_ref is None:
            self.basis_ref = self.basis_attempt_id or self.basis_workspace_path
        if not self.source_attempt_ids and self.basis_attempt_id:
            self.source_attempt_ids = [self.basis_attempt_id]
        if self.mutable is None:
            self.mutable = self.lineage_type != WorkspaceLineageType.PARTIAL_CONSUME

        if self.basis_type == WorkspaceBasisType.FRESH and self.basis_attempt_id:
            raise ValueError("fresh workspaces cannot declare basis_attempt_id")

    def is_inherited(self) -> bool:
        return self.lineage_type != WorkspaceLineageType.FRESH

    def is_salvage(self) -> bool:
        return self.lineage_type in {
            WorkspaceLineageType.SALVAGE_INHERIT,
            WorkspaceLineageType.SALVAGE_REPLAY,
            WorkspaceLineageType.PARTIAL_CONSUME,
        }

    def allows_modification(self) -> bool:
        return bool(self.mutable)

    def to_dict(self) -> dict[str, Any]:
        return {
            "workspace_id": self.workspace_id,
            "task_id": self.task_id,
            "basis_type": self.basis_type.value if self.basis_type else None,
            "basis_ref": self.basis_ref,
            "path": self.path,
            "source_attempt_ids": list(self.source_attempt_ids),
            "mutable": self.mutable,
            "created_at": self.created_at,
            "cleanup_status": self.cleanup_status.value,
            "lineage_type": self.lineage_type.value,
            "basis_attempt_id": self.basis_attempt_id,
            "basis_workspace_path": self.basis_workspace_path,
            "partial_artifacts": list(self.partial_artifacts or []),
            "metadata": dict(self.metadata),
        }

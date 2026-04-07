"""
Workspace lineage tracker for Crucible v5.4.

Tracks workspace origin for each attempt.
"""

from dataclasses import dataclass, field
from typing import Optional

from crucible.state.workspace_record import WorkspaceLineageType, WorkspaceRecord


class WorkspaceLineageTracker:
    """
    Tracks workspace lineage across attempts.
    
    Enables deterministic decision about whether to start fresh,
    inherit, or replay artifacts.
    """
    
    def __init__(self):
        """Initialize tracker."""
        self._lineage_records: dict[str, WorkspaceRecord] = {}
    
    def record_workspace(self, attempt_id: str, record: WorkspaceRecord):
        """Record workspace lineage for an attempt."""
        self._lineage_records[attempt_id] = record
    
    def get_workspace(self, attempt_id: str) -> Optional[WorkspaceRecord]:
        """Get workspace record for an attempt."""
        return self._lineage_records.get(attempt_id)
    
    def get_latest_workspace(self) -> Optional[WorkspaceRecord]:
        """Get the most recent workspace record."""
        if not self._lineage_records:
            return None
        return list(self._lineage_records.values())[-1]
    
    def should_use_fresh_workspace(self, previous_attempt_id: Optional[str] = None) -> bool:
        """Determine if fresh workspace should be used."""
        if previous_attempt_id is None:
            return True
        
        prev_record = self.get_workspace(previous_attempt_id)
        if prev_record is None:
            return True
        
        # If previous was partial, might want fresh
        return prev_record.lineage_type == WorkspaceLineageType.PARTIAL_CONSUME
    
    def should_inherit_workspace(self, previous_attempt_id: str) -> bool:
        """Determine if workspace should be inherited."""
        prev_record = self.get_workspace(previous_attempt_id)
        if prev_record is None:
            return False
        
        return prev_record.is_inherited() and prev_record.allows_modification()
    
    def get_lineage_summary(self) -> dict:
        """Get summary of all lineage records."""
        return {
            attempt_id: {
                "lineage_type": record.lineage_type.value,
                "basis_attempt_id": record.basis_attempt_id,
            }
            for attempt_id, record in self._lineage_records.items()
        }
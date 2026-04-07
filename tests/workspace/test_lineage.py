"""
Tests for workspace lineage and evidence store.

Phase 5: Workspace Lineage & Evidence Persistence
"""

import pytest

from crucible.evidence.store import EvidenceManifest, EvidenceStore
from crucible.state.workspace_record import WorkspaceLineageType, WorkspaceRecord
from crucible.workspace.lineage import WorkspaceLineageTracker


class TestWorkspaceLineageTracker:
    """Test WorkspaceLineageTracker."""
    
    def test_initialization(self):
        """Tracker initializes empty."""
        tracker = WorkspaceLineageTracker()
        assert len(tracker._lineage_records) == 0
    
    def test_record_workspace(self):
        """Can record workspace."""
        tracker = WorkspaceLineageTracker()
        record = WorkspaceRecord(lineage_type=WorkspaceLineageType.FRESH)
        
        tracker.record_workspace("attempt-1", record)
        
        assert tracker.get_workspace("attempt-1") == record
    
    def test_get_latest_workspace(self):
        """Gets latest workspace."""
        tracker = WorkspaceLineageTracker()
        
        tracker.record_workspace("attempt-1", WorkspaceRecord(lineage_type=WorkspaceLineageType.FRESH))
        tracker.record_workspace("attempt-2", WorkspaceRecord(lineage_type=WorkspaceLineageType.REPAIR_BASIS, basis_attempt_id="attempt-1"))
        
        latest = tracker.get_latest_workspace()
        assert latest.lineage_type == WorkspaceLineageType.REPAIR_BASIS
    
    def test_should_use_fresh_workspace_no_previous(self):
        """Fresh workspace when no previous."""
        tracker = WorkspaceLineageTracker()
        
        assert tracker.should_use_fresh_workspace() is True
        assert tracker.should_use_fresh_workspace(None) is True
    
    def test_should_use_fresh_workspace_with_previous(self):
        """Fresh workspace decision based on previous."""
        tracker = WorkspaceLineageTracker()
        
        # Previous was partial consume
        tracker.record_workspace("attempt-1", WorkspaceRecord(
            lineage_type=WorkspaceLineageType.PARTIAL_CONSUME,
            basis_attempt_id="attempt-0",
        ))
        
        assert tracker.should_use_fresh_workspace("attempt-1") is True
    
    def test_get_lineage_summary(self):
        """Get lineage summary."""
        tracker = WorkspaceLineageTracker()
        
        tracker.record_workspace("attempt-1", WorkspaceRecord(lineage_type=WorkspaceLineageType.FRESH))
        
        summary = tracker.get_lineage_summary()
        
        assert "attempt-1" in summary
        assert summary["attempt-1"]["lineage_type"] == "fresh"


class TestEvidenceManifest:
    """Test EvidenceManifest."""
    
    def test_creation(self):
        """Can create manifest."""
        manifest = EvidenceManifest(attempt_id="attempt-1")
        
        assert manifest.attempt_id == "attempt-1"
        assert len(manifest.artifacts) == 0
    
    def test_add_artifact(self):
        """Can add artifacts."""
        manifest = EvidenceManifest(attempt_id="attempt-1")
        
        manifest.add_artifact("file.py")
        
        assert "file.py" in manifest.artifacts
    
    def test_set_criterion_result(self):
        """Can set criterion results."""
        manifest = EvidenceManifest(attempt_id="attempt-1")
        
        manifest.set_criterion_result("test_output", True)
        
        assert manifest.criterion_results["test_output"] is True
    
    def test_all_criteria_passed(self):
        """Check if all criteria passed."""
        manifest = EvidenceManifest(attempt_id="attempt-1")
        
        manifest.set_criterion_result("c1", True)
        manifest.set_criterion_result("c2", True)
        
        assert manifest.all_criteria_passed() is True
        
        manifest.set_criterion_result("c3", False)
        assert manifest.all_criteria_passed() is False


class TestEvidenceStore:
    """Test EvidenceStore."""
    
    def test_initialization(self, tmp_path):
        """Store initializes with path."""
        store = EvidenceStore(base_path=tmp_path)
        
        assert store.base_path == tmp_path
    
    def test_store_manifest(self, tmp_path):
        """Can store manifest."""
        store = EvidenceStore(base_path=tmp_path)
        
        manifest = EvidenceManifest(attempt_id="run1-attempt-1")
        manifest.add_artifact("output.py")
        manifest.set_criterion_result("test", True)
        
        path = store.store_manifest(manifest)
        
        assert path.exists()
    
    def test_load_manifest(self, tmp_path):
        """Can load manifest."""
        store = EvidenceStore(base_path=tmp_path)
        
        manifest = EvidenceManifest(attempt_id="run1-attempt-1")
        manifest.add_artifact("output.py")
        
        store.store_manifest(manifest)
        
        loaded = store.load_manifest("run1-attempt-1")
        
        assert loaded is not None
        assert loaded.attempt_id == "run1-attempt-1"
        assert "output.py" in loaded.artifacts
    
    def test_load_nonexistent(self, tmp_path):
        """Loading nonexistent returns None."""
        store = EvidenceStore(base_path=tmp_path)
        
        result = store.load_manifest("nonexistent")
        
        assert result is None
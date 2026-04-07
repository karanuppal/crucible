"""Phase 3 tests: Artifact reference model."""

import pytest

from crucible.validation.artifact import (
    ArtifactRef, ArtifactType, compute_file_hash, create_artifact_ref,
)


class TestArtifactCreation:
    def test_create_from_real_file(self, tmp_path):
        p = tmp_path / "evidence.txt"
        p.write_text("test output")
        
        ref = create_artifact_ref(str(p), ArtifactType.LOG, "run-1")
        assert ref.exists()
        assert ref.content_hash != ""
        assert ref.producer_run_id == "run-1"
    
    def test_missing_file_rejected(self):
        with pytest.raises(FileNotFoundError):
            create_artifact_ref("/nonexistent/path.txt", ArtifactType.LOG, "run-1")


class TestIntegrity:
    def test_hash_matches_on_unchanged_file(self, tmp_path):
        p = tmp_path / "art.txt"
        p.write_text("stable content")
        ref = create_artifact_ref(str(p), ArtifactType.FILE, "run-1")
        
        assert ref.verify_integrity()
    
    def test_hash_fails_on_tampered_file(self, tmp_path):
        p = tmp_path / "art.txt"
        p.write_text("original")
        ref = create_artifact_ref(str(p), ArtifactType.FILE, "run-1")
        
        # Tamper
        p.write_text("tampered")
        
        assert not ref.verify_integrity()
    
    def test_hash_fails_on_missing_file(self, tmp_path):
        p = tmp_path / "art.txt"
        p.write_text("content")
        ref = create_artifact_ref(str(p), ArtifactType.FILE, "run-1")
        
        p.unlink()
        assert not ref.verify_integrity()


class TestSerialization:
    def test_roundtrip(self, tmp_path):
        p = tmp_path / "x.txt"
        p.write_text("hello")
        ref = create_artifact_ref(str(p), ArtifactType.LOG, "run-1")
        
        d = ref.to_dict()
        ref2 = ArtifactRef.from_dict(d)
        assert ref2.artifact_id == ref.artifact_id
        assert ref2.content_hash == ref.content_hash
        assert ref2.type == ref.type

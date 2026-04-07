"""Phase 4 tests: machine profile detection."""

import pytest

from agentic_harness.scheduler.machine_profile import (
    MachineProfile, detect_machine_profile, fallback_profile,
)


class TestDetection:
    def test_detected_profile_reasonable(self):
        p = detect_machine_profile()
        assert p.cpu_count >= 1
        assert p.total_memory_gb > 0
        assert p.platform in {"Darwin", "Linux", "Windows", "unknown"}
    
    def test_fallback_always_safe(self):
        p = fallback_profile()
        assert p.cpu_count >= 1
        assert p.total_memory_gb > 0
        assert p.source == "fallback"


class TestPersistence:
    def test_save_load_roundtrip(self, tmp_path):
        p = detect_machine_profile()
        path = str(tmp_path / "profile.json")
        p.save(path)
        
        loaded = MachineProfile.load(path)
        assert loaded.cpu_count == p.cpu_count
        assert loaded.total_memory_gb == p.total_memory_gb
        assert loaded.platform == p.platform
    
    def test_atomic_save(self, tmp_path):
        """Save should never leave a corrupted file."""
        p = detect_machine_profile()
        path = str(tmp_path / "profile.json")
        p.save(path)
        
        # File should exist and be valid JSON
        import json
        with open(path) as f:
            data = json.load(f)
        assert "cpu_count" in data

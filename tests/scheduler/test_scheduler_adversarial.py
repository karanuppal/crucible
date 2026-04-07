"""Phase 4 v2 adversarial tests: profile fail-safe, intensity wrappers, headroom."""

import pytest
import sys
import types

from agentic_harness.scheduler.machine_profile import (
    MachineProfile, detect_machine_profile, fallback_profile,
)
from agentic_harness.scheduler.intensity import (
    Intensity, classify_intensity,
)


# ─────────────────────────────────────────────────────────────────
# Machine profile fail-safe
# ─────────────────────────────────────────────────────────────────

class TestProfileFailSafe:
    def test_psutil_runtime_error_falls_back(self, monkeypatch):
        """If psutil exists but virtual_memory() raises RuntimeError, must fall back."""
        fake_psutil = types.ModuleType("psutil")
        def boom():
            raise RuntimeError("boom")
        fake_psutil.virtual_memory = boom
        monkeypatch.setitem(sys.modules, "psutil", fake_psutil)
        
        # Should not raise
        p = detect_machine_profile()
        assert p.cpu_count >= 1
        assert p.total_memory_gb > 0
    
    def test_impossible_memory_corrected(self, monkeypatch):
        """available > total should be corrected and source flagged fallback."""
        fake_psutil = types.ModuleType("psutil")
        def vm():
            class VM:
                total = 8 * (1024 ** 3)
                available = 64 * (1024 ** 3)  # impossible
            return VM()
        fake_psutil.virtual_memory = vm
        monkeypatch.setitem(sys.modules, "psutil", fake_psutil)
        
        p = detect_machine_profile()
        assert p.available_memory_gb <= p.total_memory_gb
        assert p.source == "fallback"


# ─────────────────────────────────────────────────────────────────
# Intensity classification — wrapper variants
# ─────────────────────────────────────────────────────────────────

class TestWrapperVariants:
    @pytest.mark.parametrize("cmd", [
        "python -m pytest",
        "python3 -m pytest",
        "uv run pytest",
        "poetry run pytest",
        "npx pytest",
        "PYTHONPATH=src python -m pytest",
        "pytest tests/unit",
        "pytest tests/ -q",
        "npm ci",
        "make test",
        "env PYTHONPATH=src python -m pytest",
        "bash -lc 'pytest tests/'",
        "sh -c 'pytest tests/'",
        "python -c 'import pytest; pytest.main()'",
    ])
    def test_wrapper_variants_classified_heavy(self, cmd):
        r = classify_intensity(cmd)
        assert r.intensity == Intensity.HEAVY, (
            f"{cmd!r} should be HEAVY, got {r.intensity} ({r.reason})"
        )
    
    def test_single_test_still_light(self):
        r = classify_intensity("python -m pytest tests/test_foo.py::test_bar")
        assert r.intensity == Intensity.LIGHT
    
    def test_uv_run_single_test_light(self):
        r = classify_intensity("uv run pytest tests/test_x.py::test_y")
        assert r.intensity == Intensity.LIGHT

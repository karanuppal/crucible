"""Phase 4 tests: intensity classification."""

import pytest

from crucible.scheduler.intensity import (
    Intensity, classify_intensity, IntensityClassification,
)


class TestAdversarialLooksLightButHeavy:
    def test_pytest_tests_flagged_heavy(self):
        r = classify_intensity("pytest tests/")
        assert r.intensity == Intensity.HEAVY
        assert r.adversarial_flag
    
    def test_bare_pytest_flagged_heavy(self):
        r = classify_intensity("pytest")
        assert r.intensity == Intensity.HEAVY
        assert r.adversarial_flag
    
    def test_pip_install_flagged_heavy(self):
        r = classify_intensity("pip install -r requirements.txt")
        assert r.intensity == Intensity.HEAVY
    
    def test_uv_sync_flagged_heavy(self):
        r = classify_intensity("uv sync")
        assert r.intensity == Intensity.HEAVY


class TestExplicitHeavy:
    @pytest.mark.parametrize("cmd", [
        "docker build -t x .",
        "cargo build --release",
        "npm install",
        "make all",
        "playwright test",
        "pytest -n auto",
    ])
    def test_explicit_heavy(self, cmd):
        r = classify_intensity(cmd)
        assert r.intensity == Intensity.HEAVY


class TestExplicitLight:
    @pytest.mark.parametrize("cmd", [
        "echo hello",
        "ls -la",
        "cat file.txt",
        "pytest tests/test_foo.py::test_bar",
        "pytest -k single_test",
        "ruff check .",
    ])
    def test_explicit_light(self, cmd):
        r = classify_intensity(cmd)
        assert r.intensity == Intensity.LIGHT


class TestHistoricalRuntime:
    def test_long_runtime_heavy(self):
        r = classify_intensity("custom_cmd", historical_runtime_s=120.0)
        assert r.intensity == Intensity.HEAVY
    
    def test_short_runtime_light(self):
        r = classify_intensity("custom_cmd", historical_runtime_s=1.0)
        assert r.intensity == Intensity.LIGHT


class TestTaskSizeFallback:
    def test_small_task(self):
        r = classify_intensity("unknown_cmd", task_size="S")
        assert r.intensity == Intensity.LIGHT
    
    def test_medium_task(self):
        r = classify_intensity("unknown_cmd", task_size="M")
        assert r.intensity == Intensity.MEDIUM
    
    def test_large_task(self):
        r = classify_intensity("unknown_cmd", task_size="L")
        assert r.intensity == Intensity.HEAVY

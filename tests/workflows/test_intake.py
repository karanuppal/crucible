"""Phase 5 tests: existing-project intake."""

import os
import pytest

from agentic_harness.workflows.intake import (
    IntakeReport, inspect_repo, Confidence,
)


def _make_clean_python_repo(tmp_path):
    """A clean modern Python repo with all signals."""
    (tmp_path / "pyproject.toml").write_text("""[project]
name = "test"
[tool.pytest.ini_options]
testpaths = ["tests"]
""")
    (tmp_path / "uv.lock").write_text("")
    (tmp_path / "README.md").write_text("# test")
    (tmp_path / ".git").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "conftest.py").write_text("")
    (tmp_path / ".github" / "workflows").mkdir(parents=True)
    (tmp_path / ".github" / "workflows" / "ci.yml").write_text("name: CI")
    return str(tmp_path)


def _make_messy_repo(tmp_path):
    """Has language signal but no tests, no PM, no CI."""
    (tmp_path / "main.py").write_text("print('hi')")
    (tmp_path / "setup.py").write_text("from setuptools import setup")
    (tmp_path / ".git").mkdir()
    return str(tmp_path)


def _make_ambiguous_repo(tmp_path):
    """Empty-ish, no signals."""
    (tmp_path / "data.txt").write_text("just data")
    return str(tmp_path)


class TestArchetypes:
    def test_clean_repo_classified(self, tmp_path):
        path = _make_clean_python_repo(tmp_path)
        report = inspect_repo(path)
        assert report.archetype == "clean"
        assert any(d.label == "python" for d in report.languages)
        assert any(d.label == "uv" for d in report.package_managers)
        assert any(d.label == "pytest" for d in report.test_frameworks)
        assert report.has_ci
    
    def test_messy_repo_classified(self, tmp_path):
        path = _make_messy_repo(tmp_path)
        report = inspect_repo(path)
        assert report.archetype == "messy"
        assert any(d.label == "python" for d in report.languages)
    
    def test_ambiguous_repo_surfaces_uncertainty(self, tmp_path):
        path = _make_ambiguous_repo(tmp_path)
        report = inspect_repo(path)
        assert report.archetype == "ambiguous"
        assert "no_language_detected" in report.uncertainty_flags
        assert report.has_blocking_uncertainty()


class TestNoHallucination:
    def test_no_test_framework_surfaces_uncertainty(self, tmp_path):
        (tmp_path / "pyproject.toml").write_text("[project]\nname='x'")
        (tmp_path / "uv.lock").write_text("")
        (tmp_path / ".git").mkdir()
        
        report = inspect_repo(str(tmp_path))
        assert "no_test_framework_detected" in report.uncertainty_flags
    
    def test_no_package_manager_surfaces_uncertainty(self, tmp_path):
        (tmp_path / "main.py").write_text("")
        (tmp_path / "setup.py").write_text("")
        (tmp_path / ".git").mkdir()
        
        report = inspect_repo(str(tmp_path))
        assert "no_package_manager_detected" in report.uncertainty_flags
    
    def test_missing_repo_raises(self):
        with pytest.raises(FileNotFoundError):
            inspect_repo("/nonexistent/path/xyz")


class TestPersistence:
    def test_save_load_roundtrip(self, tmp_path):
        path = _make_clean_python_repo(tmp_path)
        report = inspect_repo(path)
        
        save_path = str(tmp_path / "intake.json")
        report.save(save_path)
        
        loaded = IntakeReport.load(save_path)
        assert loaded.archetype == report.archetype
        assert len(loaded.languages) == len(report.languages)
        assert loaded.has_ci == report.has_ci

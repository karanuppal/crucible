"""Phase 5 tests: Unified project workflows."""

import os
import subprocess
import pytest

from agentic_harness.workflows.project import (
    ProjectMode, ProjectInspection, WorktreeManager, GreenfieldScaffolder,
    GitHubSetup, FirstWorkingVersionGate, inspect_existing_project,
)


class TestProjectInspection:
    def test_inspect_finds_python_project(self, tmp_path):
        # Create a fake Python project
        (tmp_path / "pyproject.toml").write_text('[project]\nname = "test"')
        (tmp_path / "tests").mkdir()
        
        inspection = inspect_existing_project(str(tmp_path))
        
        assert inspection.language == "python"
        assert inspection.has_package_manager
        assert inspection.has_tests


class TestGreenfieldScaffolder:
    def test_scaffold_creates_directory(self, tmp_path):
        scaffolder = GreenfieldScaffolder()
        
        result = scaffolder.scaffold(str(tmp_path / "myproject"), "python")
        
        assert result["project_name"] == "myproject"
        assert result["language"] == "python"
        assert os.path.exists(tmp_path / "myproject" / "pyproject.toml")
    
    def test_scaffold_uses_uv(self, tmp_path):
        scaffolder = GreenfieldScaffolder()
        
        result = scaffolder.scaffold(str(tmp_path / "proj"), "python")
        
        assert result["template"]["package_manager"] == "uv"


class TestGitHubSetup:
    def test_create_repo_returns_structure(self):
        setup = GitHubSetup()
        
        result = setup.create_repo("test-repo", private=True)
        
        assert result["name"] == "test-repo"
        assert result["private"]
        assert "url" in result
    
    def test_add_ci_workflow_creates_file(self, tmp_path):
        setup = GitHubSetup()
        
        success = setup.add_ci_workflow(
            str(tmp_path),
            "test-workflow",
            {"name": "Test", "on": "push"},
        )
        
        assert success
        assert os.path.exists(tmp_path / ".github" / "workflows" / "test-workflow.yml")


class TestFirstWorkingVersionGate:
    def test_gate_passes_with_clean_tests(self, tmp_path):
        gate = FirstWorkingVersionGate()
        
        # Create a passing test file
        (tmp_path / "test_example.py").write_text("def test_pass():\n    assert True")
        
        result = gate.run(str(tmp_path), "pytest")
        
        assert result["passed"]
    
    def test_gate_fails_with_broken_tests(self, tmp_path):
        gate = FirstWorkingVersionGate()
        
        # Create a failing test file
        (tmp_path / "test_example.py").write_text("def test_fail():\n    assert False")
        
        result = gate.run(str(tmp_path), "pytest")
        
        assert not result["passed"]


class TestWorktreeManager:
    def test_list_worktrees_handles_empty(self, tmp_path):
        # Create a temporary git repo
        subprocess.run(["git", "init"], cwd=tmp_path, capture_output=True)
        
        manager = WorktreeManager(str(tmp_path))
        worktrees = manager.list_worktrees()
        
        # At minimum should have the main worktree
        assert isinstance(worktrees, list)
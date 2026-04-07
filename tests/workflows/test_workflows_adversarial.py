"""Phase 5 v2 adversarial tests."""

import os
import shutil
import subprocess
import pytest

from agentic_harness.workflows.intake import inspect_repo, Confidence
from agentic_harness.workflows.worktree import WorktreeManager
from agentic_harness.workflows.greenfield import (
    BootstrapConfig, ProjectType, bootstrap_greenfield, load_bootstrap_state,
)
from agentic_harness.workflows.first_working_version import check_first_working_version


# ─────────────────────────────────────────────────────────────────
# Fix 1: intake — no unittest hallucination, broken archetype reachable
# ─────────────────────────────────────────────────────────────────

class TestIntakeNoHallucination:
    def test_pytest_comment_does_not_invent_pytest(self, tmp_path):
        """The word 'pytest' in a pyproject comment must not classify the repo as using pytest."""
        (tmp_path / "pyproject.toml").write_text("""# Note: we don't use pytest, prefer unittest
[project]
name = "x"
dependencies = []
""")
        (tmp_path / ".git").mkdir()
        
        report = inspect_repo(str(tmp_path))
        # Pytest must NOT be detected from a comment
        assert not any(d.label == "pytest" for d in report.test_frameworks)
    
    def test_bare_tests_dir_no_unittest_invented(self, tmp_path):
        """A pyproject.toml + tests/ dir with no real test framework signals
        must NOT invent 'unittest' as a framework."""
        (tmp_path / "pyproject.toml").write_text("[project]\nname='x'")
        (tmp_path / "uv.lock").write_text("")
        (tmp_path / ".git").mkdir()
        (tmp_path / "tests").mkdir()
        (tmp_path / "tests" / "data.txt").write_text("not a test file")
        
        report = inspect_repo(str(tmp_path))
        # No unittest invented
        assert not any(d.label == "unittest" for d in report.test_frameworks)
        # Uncertainty surfaced
        assert "no_test_framework_detected" in report.uncertainty_flags


class TestBrokenArchetypeReachable:
    def test_broken_archetype_classified(self, tmp_path):
        """A repo with language but no PM, no tests, no git, no readme = broken."""
        (tmp_path / "main.py").write_text("print('hi')")
        # No pyproject, no uv.lock, no .git, no README, no tests
        # Need a language signature though
        (tmp_path / "setup.py").write_text("from setuptools import setup")
        
        report = inspect_repo(str(tmp_path))
        assert report.archetype == "broken", f"Got {report.archetype}, languages={[d.label for d in report.languages]}"


# ─────────────────────────────────────────────────────────────────
# Fix 2: worktree reconciliation
# ─────────────────────────────────────────────────────────────────

def _init_git_repo(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    env = os.environ.copy()
    env.update({
        "GIT_AUTHOR_NAME": "test", "GIT_AUTHOR_EMAIL": "t@t.t",
        "GIT_COMMITTER_NAME": "test", "GIT_COMMITTER_EMAIL": "t@t.t",
    })
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=repo, check=True, env=env)
    (repo / "README.md").write_text("x")
    subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True, env=env)
    subprocess.run(["git", "-C", str(repo), "commit", "-q", "-m", "init"], check=True, env=env)
    return str(repo)


class TestWorktreeReconciliation:
    def test_git_broken_marks_all_active_stale(self, tmp_path):
        """If git is broken/unreachable, fail-closed: all active worktrees marked stale."""
        repo = _init_git_repo(tmp_path)
        state_path = str(tmp_path / "state.json")
        
        mgr1 = WorktreeManager(repo, state_path=state_path)
        record = mgr1.create_worktree()
        
        # Break git: nuke the .git directory
        shutil.rmtree(os.path.join(repo, ".git"))
        
        # Reload — git is broken, must fail closed
        mgr2 = WorktreeManager(repo, state_path=state_path)
        loaded = mgr2.get(record.worktree_id)
        assert loaded.status == "stale"
    
    def test_missing_worktree_marked_stale(self, tmp_path):
        repo = _init_git_repo(tmp_path)
        state_path = str(tmp_path / "state.json")
        
        mgr1 = WorktreeManager(repo, state_path=state_path)
        record = mgr1.create_worktree()
        
        # Simulate out-of-band deletion of the worktree directory
        shutil.rmtree(record.path)
        
        # Reload — should detect and mark stale
        mgr2 = WorktreeManager(repo, state_path=state_path)
        loaded = mgr2.get(record.worktree_id)
        assert loaded.status == "stale"
        # Should not appear in active list
        active = mgr2.list_active()
        assert record.worktree_id not in [w.worktree_id for w in active]


# ─────────────────────────────────────────────────────────────────
# Fix 3: greenfield resume verifies artifacts
# ─────────────────────────────────────────────────────────────────

class TestGreenfieldResumeIntegrity:
    def test_resume_repairs_missing_artifacts(self, tmp_path):
        """If a completed step's artifact is deleted, resume must re-create it."""
        target = str(tmp_path / "proj")
        config = BootstrapConfig(
            project_name="proj",
            project_type=ProjectType.PYTHON_LIB,
            target_dir=target,
            description="x",
        )
        state_path = str(tmp_path / "boot.json")
        
        # Initial bootstrap
        bootstrap_greenfield(config, state_path=state_path)
        
        # Delete a critical artifact
        os.remove(os.path.join(target, "pyproject.toml"))
        
        # Reload state and resume — should repair
        loaded = load_bootstrap_state(state_path)
        result = bootstrap_greenfield(config, state_path=state_path, state=loaded)
        
        assert result.is_complete
        assert os.path.isfile(os.path.join(target, "pyproject.toml"))
    
    def test_resume_doesnt_falsely_claim_complete(self, tmp_path):
        """If state says complete but artifacts are missing, resume must rebuild."""
        target = str(tmp_path / "proj")
        config = BootstrapConfig(
            project_name="proj",
            project_type=ProjectType.PYTHON_LIB,
            target_dir=target,
        )
        state_path = str(tmp_path / "boot.json")
        
        bootstrap_greenfield(config, state_path=state_path)
        
        # Delete the entire pyproject + src
        os.remove(os.path.join(target, "pyproject.toml"))
        shutil.rmtree(os.path.join(target, "src"))
        
        loaded = load_bootstrap_state(state_path)
        # is_complete should NOT survive a re-run with missing artifacts
        result = bootstrap_greenfield(config, state_path=state_path, state=loaded)
        # After re-run, should be repaired
        assert os.path.isfile(os.path.join(target, "pyproject.toml"))
        assert os.path.isdir(os.path.join(target, "src"))


# ─────────────────────────────────────────────────────────────────
# Fix 4: first-working-version anti-forgery
# ─────────────────────────────────────────────────────────────────

class TestFirstWorkingVersionAntiForgery:
    def test_forgery_with_no_test_files_rejected(self, tmp_path):
        """Forged 'pytest output' without real test files on disk should fail."""
        script = tmp_path / "fake.sh"
        script.write_text("#!/bin/bash\necho '1 passed in 0.01s'\nexit 0\n")
        script.chmod(0o755)
        
        result = check_first_working_version(
            str(tmp_path),
            test_command=[str(script)],
        )
        assert not result.is_working
    
    def test_real_test_file_required(self, tmp_path):
        """Even with passing output, must have real test_*.py file."""
        # Just a regular .py file, NOT a test_*.py
        (tmp_path / "main.py").write_text("def x(): pass")
        
        script = tmp_path / "fake.sh"
        script.write_text("#!/bin/bash\necho '1 passed'\nexit 0\n")
        script.chmod(0o755)
        
        result = check_first_working_version(
            str(tmp_path),
            test_command=[str(script)],
        )
        assert not result.is_working
    
    def test_real_test_file_accepted(self, tmp_path):
        (tmp_path / "test_real.py").write_text("def test_x(): pass")
        
        script = tmp_path / "fake.sh"
        # Output must reference the actual test file
        script.write_text("#!/bin/bash\necho 'test_real.py::test_x PASSED'\necho '1 passed'\nexit 0\n")
        script.chmod(0o755)
        
        result = check_first_working_version(
            str(tmp_path),
            test_command=[str(script)],
        )
        assert result.is_working
    
    def test_forgery_with_test_file_but_no_reference_rejected(self, tmp_path):
        """Test file exists but output doesn't reference it → rejected."""
        (tmp_path / "test_real.py").write_text("def test_x(): pass")
        
        script = tmp_path / "fake.sh"
        # Output says 1 passed but doesn't reference the actual test file
        script.write_text("#!/bin/bash\necho '1 passed in 0.01s'\nexit 0\n")
        script.chmod(0o755)
        
        result = check_first_working_version(
            str(tmp_path),
            test_command=[str(script)],
        )
        assert not result.is_working
        assert "forgery" in result.error.lower() or "reference" in result.error.lower()

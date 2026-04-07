"""Phase 5 tests: worktree isolation."""

import os
import subprocess
import pytest

from agentic_harness.workflows.worktree import WorktreeManager, WorktreeError


def _init_repo(tmp_path):
    """Initialize a git repo in tmp_path."""
    repo = tmp_path / "repo"
    repo.mkdir()
    env = os.environ.copy()
    env["GIT_AUTHOR_NAME"] = "test"
    env["GIT_AUTHOR_EMAIL"] = "test@test.test"
    env["GIT_COMMITTER_NAME"] = "test"
    env["GIT_COMMITTER_EMAIL"] = "test@test.test"
    
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=repo, check=True, env=env)
    (repo / "README.md").write_text("# test")
    subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True, env=env)
    subprocess.run(["git", "-C", str(repo), "commit", "-q", "-m", "init"], check=True, env=env)
    return str(repo)


class TestWorktreeIsolation:
    def test_create_worktree(self, tmp_path):
        repo = _init_repo(tmp_path)
        mgr = WorktreeManager(repo)
        
        record = mgr.create_worktree(base_branch="main")
        assert os.path.isdir(record.path)
        assert record.branch.startswith("build/")
    
    def test_worktree_changes_dont_bleed_into_main(self, tmp_path):
        repo = _init_repo(tmp_path)
        mgr = WorktreeManager(repo)
        
        record = mgr.create_worktree()
        
        # Make change in worktree
        new_file = os.path.join(record.path, "feature.py")
        with open(new_file, "w") as f:
            f.write("# new feature")
        
        # Main repo should still be clean
        assert mgr.main_repo_clean()
        # Main repo should NOT have the new file
        assert not os.path.exists(os.path.join(repo, "feature.py"))
    
    def test_concurrent_worktrees_isolated(self, tmp_path):
        repo = _init_repo(tmp_path)
        mgr = WorktreeManager(repo)
        
        wt1 = mgr.create_worktree()
        wt2 = mgr.create_worktree()
        
        # Each worktree gets its own file
        with open(os.path.join(wt1.path, "a.py"), "w") as f:
            f.write("a")
        with open(os.path.join(wt2.path, "b.py"), "w") as f:
            f.write("b")
        
        # Worktrees don't see each other
        assert not os.path.exists(os.path.join(wt1.path, "b.py"))
        assert not os.path.exists(os.path.join(wt2.path, "a.py"))
        # Main is clean
        assert mgr.main_repo_clean()
    
    def test_remove_worktree(self, tmp_path):
        repo = _init_repo(tmp_path)
        mgr = WorktreeManager(repo)
        record = mgr.create_worktree()
        
        mgr.remove_worktree(record.worktree_id, force=True)
        assert mgr.get(record.worktree_id).status == "removed"


class TestPersistence:
    def test_state_survives_restart(self, tmp_path):
        repo = _init_repo(tmp_path)
        state_path = str(tmp_path / "wt_state.json")
        
        mgr1 = WorktreeManager(repo, state_path=state_path)
        record = mgr1.create_worktree()
        
        mgr2 = WorktreeManager(repo, state_path=state_path)
        loaded = mgr2.get(record.worktree_id)
        assert loaded is not None
        assert loaded.path == record.path


class TestErrors:
    def test_missing_repo_raises(self):
        with pytest.raises(WorktreeError):
            WorktreeManager("/nonexistent/repo/xyz")

"""Phase 7 tests: fan-in integration workflow."""

import os
import subprocess
import pytest

from agentic_harness.integration.fan_in import (
    FanInIntegrator, SubAgentOutput, IntegrationStatus, IntegrationError,
)


def _git_env():
    env = os.environ.copy()
    env.update({
        "GIT_AUTHOR_NAME": "test", "GIT_AUTHOR_EMAIL": "t@t.t",
        "GIT_COMMITTER_NAME": "test", "GIT_COMMITTER_EMAIL": "t@t.t",
    })
    return env


def _init_repo(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    env = _git_env()
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=repo, check=True, env=env)
    (repo / "README.md").write_text("# test\n")
    subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True, env=env)
    subprocess.run(["git", "-C", str(repo), "commit", "-q", "-m", "init"], check=True, env=env)
    return str(repo)


def _create_branch_with_change(repo, branch, file, content):
    env = _git_env()
    subprocess.run(["git", "-C", repo, "checkout", "-b", branch, "main"], check=True, env=env, capture_output=True)
    with open(os.path.join(repo, file), "w") as f:
        f.write(content)
    subprocess.run(["git", "-C", repo, "add", "-A"], check=True, env=env)
    subprocess.run(["git", "-C", repo, "commit", "-q", "-m", f"add {file}"], check=True, env=env)
    subprocess.run(["git", "-C", repo, "checkout", "main"], check=True, env=env, capture_output=True)


class TestFanInIntegration:
    def test_clean_merge(self, tmp_path):
        repo = _init_repo(tmp_path)
        _create_branch_with_change(repo, "feature/a", "a.py", "A = 1\n")
        _create_branch_with_change(repo, "feature/b", "b.py", "B = 2\n")
        
        integrator = FanInIntegrator(repo)
        outputs = [
            SubAgentOutput(task_id="t1", run_id="r1", worktree_path=repo,
                            branch_name="feature/a", artifact_paths=["a.py"]),
            SubAgentOutput(task_id="t2", run_id="r2", worktree_path=repo,
                            branch_name="feature/b", artifact_paths=["b.py"]),
        ]
        
        result = integrator.integrate(outputs)
        assert result.status == IntegrationStatus.INTEGRATED
        assert "a.py" in result.integrated_paths
        assert "b.py" in result.integrated_paths
    
    def test_conflict_detected(self, tmp_path):
        repo = _init_repo(tmp_path)
        _create_branch_with_change(repo, "feature/a", "shared.py", "VERSION = 'a'\n")
        _create_branch_with_change(repo, "feature/b", "shared.py", "VERSION = 'b'\n")
        
        integrator = FanInIntegrator(repo)
        outputs = [
            SubAgentOutput(task_id="t1", run_id="r1", worktree_path=repo,
                            branch_name="feature/a", artifact_paths=["shared.py"]),
            SubAgentOutput(task_id="t2", run_id="r2", worktree_path=repo,
                            branch_name="feature/b", artifact_paths=["shared.py"]),
        ]
        
        result = integrator.integrate(outputs)
        assert result.status == IntegrationStatus.CONFLICT
        assert len(result.conflicts) > 0
        assert any("shared.py" in c.file_path for c in result.conflicts)
    
    def test_overlap_detection(self, tmp_path):
        repo = _init_repo(tmp_path)
        _create_branch_with_change(repo, "feature/a", "shared.py", "A\n")
        _create_branch_with_change(repo, "feature/b", "shared.py", "B\n")
        _create_branch_with_change(repo, "feature/c", "other.py", "C\n")
        
        integrator = FanInIntegrator(repo)
        outputs = [
            SubAgentOutput(task_id="t1", run_id="r1", worktree_path=repo, branch_name="feature/a"),
            SubAgentOutput(task_id="t2", run_id="r2", worktree_path=repo, branch_name="feature/b"),
            SubAgentOutput(task_id="t3", run_id="r3", worktree_path=repo, branch_name="feature/c"),
        ]
        
        overlaps = integrator.detect_overlap(outputs)
        assert "shared.py" in overlaps
        assert set(overlaps["shared.py"]) == {"t1", "t2"}
        assert "other.py" not in overlaps
    
    def test_empty_outputs(self, tmp_path):
        repo = _init_repo(tmp_path)
        integrator = FanInIntegrator(repo)
        result = integrator.integrate([])
        assert result.status == IntegrationStatus.PENDING


class TestHardFailure:
    def test_nonexistent_branch_fails_closed(self, tmp_path):
        """Merging a missing branch must NOT silently report INTEGRATED."""
        repo = _init_repo(tmp_path)
        integrator = FanInIntegrator(repo)
        outputs = [
            SubAgentOutput(
                task_id="t1", run_id="r1", worktree_path=repo,
                branch_name="nonexistent/branch", artifact_paths=["x.py"],
            ),
        ]
        result = integrator.integrate(outputs)
        assert result.status == IntegrationStatus.FAILED
        assert result.error
        assert "nonexistent/branch" in result.error


class TestErrors:
    def test_missing_repo_raises(self):
        with pytest.raises(IntegrationError):
            FanInIntegrator("/nonexistent/path/xyz")
    
    def test_to_report_serializable(self, tmp_path):
        repo = _init_repo(tmp_path)
        integrator = FanInIntegrator(repo)
        result = integrator.integrate([])
        report = integrator.to_report(result)
        assert "status" in report
        assert "conflict_count" in report

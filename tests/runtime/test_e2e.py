"""Phase 8 e2e: Full Crucible flow test.

Tests: lint → run → status → watch → resume

Note: These tests must be run via `uv run pytest` from the crucible project root,
which installs the package in editable mode.
"""

import json
import os
import subprocess
import sys
import tempfile
import pytest


# Run CLI via venv python with PYTHONPATH set to include src
SRC_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
VENV_PY = os.path.join(os.getcwd(), ".venv", "bin", "python")
CRUCIBLE_CLI = [VENV_PY, "-m", "crucible.runtime.cli"]
# Also set PYTHONPATH to include src
_env = os.environ.copy()
_env["PYTHONPATH"] = SRC_DIR


def _run_cli(args: list[str], timeout: int = 30):
    result = subprocess.run(
        CRUCIBLE_CLI + args,
        capture_output=True,
        text=True,
        timeout=timeout,
        env=_env,
    )
    return result


def _good_plan():
    return {
        "spec": "build a thing",
        "project_id": "e2e-test",
        "build_id": "build-1",
        "tasks": [
            {
                "task_id": "implement-foo",
                "description": "implement src/foo.py with tests in tests/test_foo.py",
                "criteria": [
                    {
                        "criterion_id": "c1",
                        "criterion_class": "must_pass",
                        "triple": {
                            "build_target": "src/foo.py",
                            "verification_command": "python -c 'import src.foo; print(\"OK\")'",
                            "expected_output": "OKPASS",
                        },
                    }
                ],
                "role": "builder",
                "intensity_hint": "S",
            }
        ],
    }


class TestFullFlow:
    def test_lint_rejects_bad_plan(self, tmp_path):
        bad = {"spec": "x", "project_id": "p", "build_id": "b", "tasks": []}
        path = tmp_path / "bad.json"
        path.write_text(json.dumps(bad))
        
        r = _run_cli(["lint-plan", str(path)])
        assert r.returncode == 2
    
    def test_lint_accepts_good_plan(self, tmp_path):
        plan = _good_plan()
        path = tmp_path / "good.json"
        path.write_text(json.dumps(plan))
        
        r = _run_cli(["lint-plan", str(path)])
        assert r.returncode == 0
    
    def test_run_creates_run_directory(self, tmp_path):
        plan = _good_plan()
        path = tmp_path / "plan.json"
        path.write_text(json.dumps(plan))
        runs_dir = tmp_path / "runs"
        
        r = _run_cli(["--runs-dir", str(runs_dir), "run", str(path)])
        assert r.returncode == 0
        
        run_dirs = list(runs_dir.iterdir())
        assert len(run_dirs) == 1
        run_id = run_dirs[0].name
        
        # Check run.json exists
        assert (run_dirs[0] / "run.json").exists()
        
        return run_id
    
    def test_status_returns_run_info(self, tmp_path):
        plan = _good_plan()
        path = tmp_path / "plan.json"
        path.write_text(json.dumps(plan))
        runs_dir = tmp_path / "runs"
        
        # Run
        _run_cli(["--runs-dir", str(runs_dir), "run", str(path)])
        run_id = list(runs_dir.iterdir())[0].name
        
        # Status
        r = _run_cli(["--runs-dir", str(runs_dir), "status", run_id])
        assert r.returncode == 0
        assert run_id in r.stdout
    
    def test_watch_streams_events(self, tmp_path):
        plan = _good_plan()
        path = tmp_path / "plan.json"
        path.write_text(json.dumps(plan))
        runs_dir = tmp_path / "runs"
        
        # Run
        _run_cli(["--runs-dir", str(runs_dir), "run", str(path)])
        run_id = list(runs_dir.iterdir())[0].name
        
        # Watch
        r = _run_cli(["--runs-dir", str(runs_dir), "watch", run_id, "--jsonl", "--from", "0"])
        assert r.returncode == 0
        lines = [l for l in r.stdout.strip().split("\n") if l]
        assert len(lines) >= 1
        # First line should be an event with event_id
        first = json.loads(lines[0])
        assert "event_id" in first
    
    def test_resume_nonterminal_run(self, tmp_path):
        plan = _good_plan()
        path = tmp_path / "plan.json"
        path.write_text(json.dumps(plan))
        runs_dir = tmp_path / "runs"
        
        # Run
        _run_cli(["--runs-dir", str(runs_dir), "run", str(path)])
        run_id = list(runs_dir.iterdir())[0].name
        
        # Resume
        r = _run_cli(["--runs-dir", str(runs_dir), "resume", run_id])
        assert r.returncode == 0
        assert "reconciled" in r.stdout.lower() or "resumed" in r.stdout.lower()
    
    def test_resume_unknown_run_fails(self, tmp_path):
        r = _run_cli(["--runs-dir", str(tmp_path / "runs"), "resume", "nonexistent"])
        assert r.returncode == 4
    
    def test_status_unknown_run_fails(self, tmp_path):
        r = _run_cli(["--runs-dir", str(tmp_path / "runs"), "status", "nonexistent"])
        assert r.returncode == 4


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
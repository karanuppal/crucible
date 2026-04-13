"""G5: `crucible resume` must actually execute the run, not just log a note.

`crucible run --detach` must actually start a background process.
"""

import json
import os
import subprocess
import sys
import time
import pytest


CLI = [sys.executable, "-m", "crucible.runtime.cli"]


def _run(args, timeout=30):
    return subprocess.run(CLI + args, capture_output=True, text=True, timeout=timeout)


def _good_plan(cmd="echo PASSED_OK", expected="PASSED_OK", build_target="non-path-target"):
    return {
        "spec": "resume execution test",
        "project_id": "resume-test",
        "build_id": "b1",
        "tasks": [
            {
                "task_id": "task-a",
                "description": "verify src/foo.py with tests/test_foo.py",
                "criteria": [{
                    "criterion_id": "c1",
                    "criterion_class": "must_pass",
                    "triple": {
                        "build_target": build_target,
                        "verification_command": cmd,
                        "expected_output": expected,
                    },
                }],
                "role": "builder",
                "intensity_hint": "S",
            }
        ],
    }


class TestResumeExecution:
    def test_resume_passes_completes(self, tmp_path):
        """Resume of a non-terminal run should drive it to a terminal state."""
        runs_dir = str(tmp_path / "runs")
        plan_path = tmp_path / "plan.json"
        plan_path.write_text(json.dumps(_good_plan()))
        
        # Create the run record without actually executing it by manually
        # creating just the run dir + manifest + tasks snapshot. Easiest
        # path: use create_run_store directly.
        from crucible.runtime.run_store import create_run_store
        from crucible.runtime.preflight import lint_plan
        
        plan = json.loads(plan_path.read_text())
        normalized = lint_plan(plan).normalized_plan or plan
        store, manifest = create_run_store(
            run_id=None,
            project_id=normalized["project_id"],
            build_id=normalized["build_id"],
            spec_text=normalized.get("spec", ""),
            task_plan=normalized,
            runs_root=runs_dir,
            workspace_root=str(tmp_path),
        )
        
        # Run should NOT be terminal yet
        assert not store.is_terminal()
        
        # Resume: must actually execute and complete
        r = _run(["--runs-dir", runs_dir, "resume", manifest.run_id])
        assert r.returncode == 0, f"got {r.returncode}\n{r.stdout}\n{r.stderr}"
        assert "run_succeeded" in r.stdout.lower()
        
        # Result file must exist now
        run_dir = os.path.join(runs_dir, manifest.run_id)
        assert os.path.isfile(os.path.join(run_dir, "result.json"))
    
    def test_resume_failing_run_returns_three(self, tmp_path):
        runs_dir = str(tmp_path / "runs")
        from crucible.runtime.run_store import create_run_store
        from crucible.runtime.preflight import lint_plan
        
        plan = _good_plan(cmd="false", expected="NEVER_GONNA_HAPPEN")
        normalized = lint_plan(plan).normalized_plan or plan
        store, manifest = create_run_store(
            run_id=None,
            project_id=normalized["project_id"],
            build_id=normalized["build_id"],
            spec_text=normalized.get("spec", ""),
            task_plan=normalized,
            runs_root=runs_dir,
            workspace_root=str(tmp_path),
        )
        
        r = _run(["--runs-dir", runs_dir, "resume", manifest.run_id])
        assert r.returncode == 3
        assert "run_failed" in r.stdout.lower()
    
    def test_resume_already_terminal_returns_correct_code(self, tmp_path):
        runs_dir = str(tmp_path / "runs")
        plan_path = tmp_path / "plan.json"
        plan_path.write_text(json.dumps(_good_plan()))
        
        # Run to completion first
        r = _run(["--runs-dir", runs_dir, "run", str(plan_path)])
        assert r.returncode == 0
        run_id = os.listdir(runs_dir)[0]
        
        # Resume an already-terminal run
        r = _run(["--runs-dir", runs_dir, "resume", run_id])
        assert r.returncode == 0
        assert "already terminal" in r.stdout.lower() or "run_succeeded" in r.stdout.lower()
    
    def test_resume_unknown_returns_four(self, tmp_path):
        runs_dir = str(tmp_path / "runs")
        os.makedirs(runs_dir, exist_ok=True)
        r = _run(["--runs-dir", runs_dir, "resume", "nonexistent"])
        assert r.returncode == 4


class TestDetachExecution:
    def test_detach_starts_background_process(self, tmp_path):
        runs_dir = str(tmp_path / "runs")
        plan_path = tmp_path / "plan.json"
        plan_path.write_text(json.dumps(_good_plan()))
        
        r = _run(["--runs-dir", runs_dir, "run", str(plan_path), "--detach"])
        assert r.returncode == 0
        assert "detached" in r.stdout.lower() or "pid" in r.stdout.lower()
        
        # The run dir should exist (created before detach)
        run_dirs = os.listdir(runs_dir)
        assert len(run_dirs) == 1
        
        # Wait a moment for the background process to finish
        for _ in range(50):
            result_path = os.path.join(runs_dir, run_dirs[0], "result.json")
            if os.path.isfile(result_path):
                break
            time.sleep(0.1)
        
        # The detached process should have driven the run to terminal
        result_path = os.path.join(runs_dir, run_dirs[0], "result.json")
        assert os.path.isfile(result_path), "detached process never completed run"
        result = json.loads(open(result_path).read())
        assert result["terminal_status"] == "run_succeeded"

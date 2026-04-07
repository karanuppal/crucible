"""Round-2 fix: `crucible resume` must skip already-winning task attempts.

The round-2 reviewer caught that resume re-executed completed tasks,
which is dangerous for any side-effectful verification command.
"""

import json
import os
import subprocess
import sys
import time
import pytest

from crucible.runtime.preflight import lint_plan
from crucible.runtime.run_executor import execute_run
from crucible.runtime.run_store import create_run_store
from crucible.runtime.local_shell_adapter import LocalShellAdapter


CLI = [sys.executable, "-m", "crucible.runtime.cli"]


def _counter_plan(counter_path):
    """Plan whose verification command increments a counter file as a side effect."""
    return {
        "spec": "incremental resume test",
        "project_id": "incr-resume",
        "build_id": "b1",
        "tasks": [{
            "task_id": "counter-task",
            "description": "verify src/foo.py with tests/test_foo.py via counter",
            "criteria": [{
                "criterion_id": "c1",
                "criterion_class": "must_pass",
                "triple": {
                    "build_target": "non-path-target",
                    "verification_command": (
                        f"COUNT=$(cat {counter_path} 2>/dev/null || echo 0); "
                        f"NEW=$((COUNT + 1)); "
                        f"echo $NEW > {counter_path}; "
                        f"echo INCREMENTED_TO_$NEW"
                    ),
                    "expected_output": "INCREMENTED",
                },
            }],
            "role": "builder",
            "intensity_hint": "S",
        }],
    }


class TestResumeIncremental:
    def test_resume_does_not_rerun_winning_task(self, tmp_path):
        counter = tmp_path / "counter.txt"
        plan = _counter_plan(str(counter))
        
        runs_dir = str(tmp_path / "runs")
        normalized = lint_plan(plan).normalized_plan or plan
        store, manifest = create_run_store(
            run_id=None, project_id=normalized["project_id"], build_id=normalized["build_id"],
            spec_text=normalized.get("spec", ""), task_plan=normalized,
            runs_root=runs_dir,
        )
        
        # First execution: should run the verification (counter → 1)
        summary1 = execute_run(
            store=store, manifest=manifest, plan=normalized,
            adapter_factory=lambda s: [LocalShellAdapter()],
            workspace_root=str(tmp_path),
        )
        assert summary1.terminal_status == "complete"
        assert counter.read_text().strip() == "1", f"counter wrong: {counter.read_text()}"
        
        # The result.json now exists; manually clear it so resume sees a
        # non-terminal run with a winning attempt already on disk
        os.unlink(store.result_path)
        
        # Resume: must NOT re-execute (counter must stay at 1)
        r = subprocess.run(
            CLI + ["--runs-dir", runs_dir, "resume", manifest.run_id],
            capture_output=True, text=True, timeout=30,
        )
        assert r.returncode == 0, f"got {r.returncode}\n{r.stdout}\n{r.stderr}"
        
        final_count = counter.read_text().strip()
        assert final_count == "1", (
            f"resume re-executed completed task — counter is {final_count}, expected 1"
        )
    
    def test_resume_runs_only_failed_tasks(self, tmp_path):
        """Two-task plan: one passes, one fails. Resume should only retry the failed one."""
        counter = tmp_path / "counter.txt"
        good_marker = tmp_path / "good_marker.txt"
        
        plan = {
            "spec": "mixed resume test",
            "project_id": "mixed",
            "build_id": "b1",
            "tasks": [
                {
                    "task_id": "good-task",
                    "description": "verify src/good.py with tests/test_good.py",
                    "criteria": [{
                        "criterion_id": "c1",
                        "criterion_class": "must_pass",
                        "triple": {
                            "build_target": "non-path-target",
                            "verification_command": (
                                f"COUNT=$(cat {good_marker} 2>/dev/null || echo 0); "
                                f"NEW=$((COUNT + 1)); "
                                f"echo $NEW > {good_marker}; "
                                f"echo GOOD_RAN_$NEW"
                            ),
                            "expected_output": "GOOD_RAN",
                        },
                    }],
                    "role": "builder", "intensity_hint": "S",
                },
                {
                    "task_id": "bad-task",
                    "description": "verify src/bad.py with tests/test_bad.py",
                    "criteria": [{
                        "criterion_id": "c1",
                        "criterion_class": "must_pass",
                        "triple": {
                            "build_target": "non-path-target",
                            "verification_command": "echo FAIL_OUTPUT",
                            "expected_output": "PASS_OUTPUT",
                        },
                    }],
                    "role": "builder", "intensity_hint": "S",
                },
            ],
        }
        
        runs_dir = str(tmp_path / "runs")
        normalized = lint_plan(plan).normalized_plan or plan
        store, manifest = create_run_store(
            run_id=None, project_id=normalized["project_id"], build_id=normalized["build_id"],
            spec_text=normalized.get("spec", ""), task_plan=normalized,
            runs_root=runs_dir,
        )
        
        # First execution
        summary1 = execute_run(
            store=store, manifest=manifest, plan=normalized,
            adapter_factory=lambda s: [LocalShellAdapter()],
            workspace_root=str(tmp_path),
        )
        # good-task passed (counter → 1), bad-task failed
        assert "good-task" in summary1.completed_tasks
        assert "bad-task" in summary1.failed_tasks
        assert good_marker.read_text().strip() == "1"
        
        # Clear terminal marker so resume re-runs
        os.unlink(store.result_path)
        
        # Resume: good-task should be skipped, bad-task should be re-attempted
        r = subprocess.run(
            CLI + ["--runs-dir", runs_dir, "resume", manifest.run_id],
            capture_output=True, text=True, timeout=30,
        )
        # bad-task fails again so exit 3
        assert r.returncode == 3
        
        # good_marker must NOT have been incremented
        assert good_marker.read_text().strip() == "1", (
            f"resume re-executed good-task — counter is {good_marker.read_text().strip()}"
        )

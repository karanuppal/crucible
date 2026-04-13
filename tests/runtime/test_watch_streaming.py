"""Round-2 fix: `crucible watch --follow` must actually stream new events."""

import json
import os
import subprocess
import sys
import threading
import time
import pytest

from crucible.runtime.preflight import lint_plan
from crucible.runtime.run_store import create_run_store


CLI = [sys.executable, "-m", "crucible.runtime.cli"]


def _slow_plan(seconds=1.5):
    return {
        "spec": "watch streaming test",
        "project_id": "watch-stream",
        "build_id": "b1",
        "tasks": [{
            "task_id": "slow-task",
            "description": "verify src/foo.py with tests/test_foo.py after sleep",
            "criteria": [{
                "criterion_id": "c1",
                "criterion_class": "must_pass",
                "triple": {
                    "build_target": "non-path-target",
                    "verification_command": f"sleep {seconds}; echo PASSED_LATER",
                    "expected_output": "PASSED_LATER",
                },
            }],
            "role": "builder",
            "intensity_hint": "S",
        }],
    }


class TestWatchFollowStreams:
    def test_watch_without_follow_returns_only_existing_events(self, tmp_path):
        runs_dir = tmp_path / "runs"
        plan = _slow_plan(seconds=0.5)
        normalized = lint_plan(plan).normalized_plan or plan
        store, manifest = create_run_store(
            run_id=None, project_id=normalized["project_id"], build_id=normalized["build_id"],
            spec_text=normalized.get("spec", ""), task_plan=normalized,
            runs_root=str(runs_dir),
        )
        
        # Run with --watch (no follow) should return immediately
        r = subprocess.run(
            CLI + ["--runs-dir", str(runs_dir), "watch", manifest.run_id, "--jsonl", "--from", "0"],
            capture_output=True, text=True, timeout=10,
        )
        # Run hasn't been executed at all → only run_started event
        records = [json.loads(l) for l in r.stdout.strip().split("\n") if l]
        assert records[0]["event"] == "plan_state"
        events = records[1:]
        types = [e["type"] for e in events]
        assert "run_started" in types
        assert "run_terminal" not in types  # not run yet
    
    def test_watch_follow_streams_until_terminal(self, tmp_path):
        """Start a slow run in the background, then watch --follow.
        
        The follow loop must pick up new events as they're written and
        return only when the run is terminal.
        """
        runs_dir = tmp_path / "runs"
        plan = _slow_plan(seconds=1.5)
        plan_path = tmp_path / "plan.json"
        plan_path.write_text(json.dumps(plan))
        
        # Spawn a foreground run in the background (Popen)
        run_proc = subprocess.Popen(
            CLI + ["--runs-dir", str(runs_dir), "run", str(plan_path)],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        )
        
        # Give it a moment to create the run dir
        deadline = time.time() + 5
        run_id = None
        while time.time() < deadline:
            if runs_dir.exists():
                dirs = [d for d in os.listdir(runs_dir) if d.startswith("run-")]
                if dirs:
                    run_id = dirs[0]
                    break
            time.sleep(0.05)
        assert run_id is not None, "run dir never created"
        
        # Watch --follow should block until the run is terminal
        watch_started = time.time()
        watch_proc = subprocess.run(
            CLI + ["--runs-dir", str(runs_dir), "watch", run_id, "--jsonl",
                   "--from", "0", "--follow", "--follow-timeout", "30"],
            capture_output=True, text=True, timeout=30,
        )
        watch_elapsed = time.time() - watch_started
        
        run_proc.wait(timeout=10)
        
        # Watch must have waited at least most of the sleep duration
        assert watch_elapsed >= 0.5, f"watch returned too fast: {watch_elapsed}s"
        
        # And it must have collected the terminal event
        records = [json.loads(l) for l in watch_proc.stdout.strip().split("\n") if l]
        assert records[0]["event"] == "plan_state"
        events = records[1:]
        types = [e["type"] for e in events]
        assert "run_terminal" in types, f"no run_terminal in events: {types}"

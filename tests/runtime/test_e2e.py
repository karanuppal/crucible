"""Phase 8 e2e: Full Crucible flow test.

Tests: lint → run → status → watch → resume
"""

import json
import os
import subprocess
import sys
import pytest


CRUCIBLE_CLI = [sys.executable, "-m", "crucible.runtime.cli"]


def _run_cli(args, timeout=30):
    return subprocess.run(
        CRUCIBLE_CLI + args,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


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
                            "verification_command": "echo 'OK_FOO is here'",
                            "expected_output": "OK_FOO",
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
        path = tmp_path / "good.json"
        path.write_text(json.dumps(_good_plan()))
        r = _run_cli(["lint-plan", str(path)])
        assert r.returncode == 0, r.stderr

    def test_run_creates_run_directory(self, tmp_path):
        path = tmp_path / "plan.json"
        path.write_text(json.dumps(_good_plan()))
        runs_dir = tmp_path / "runs"
        r = _run_cli(["--runs-dir", str(runs_dir), "run", str(path)])
        assert r.returncode == 0, r.stderr
        run_dirs = list(runs_dir.iterdir())
        assert len(run_dirs) == 1
        assert (run_dirs[0] / "run.json").exists()
        assert (run_dirs[0] / "events.jsonl").exists()
        assert (run_dirs[0] / "tasks.json").exists()
        assert (run_dirs[0] / "result.json").exists()
        # Foreground run with default in-memory adapter should complete
        assert "terminal_status: complete" in r.stdout

    def test_status_returns_run_info(self, tmp_path):
        path = tmp_path / "plan.json"
        path.write_text(json.dumps(_good_plan()))
        runs_dir = tmp_path / "runs"
        _run_cli(["--runs-dir", str(runs_dir), "run", str(path)])
        run_id = list(runs_dir.iterdir())[0].name
        r = _run_cli(["--runs-dir", str(runs_dir), "status", run_id])
        assert r.returncode == 0
        assert run_id in r.stdout

    def test_watch_streams_events(self, tmp_path):
        path = tmp_path / "plan.json"
        path.write_text(json.dumps(_good_plan()))
        runs_dir = tmp_path / "runs"
        _run_cli(["--runs-dir", str(runs_dir), "run", str(path)])
        run_id = list(runs_dir.iterdir())[0].name
        r = _run_cli(["--runs-dir", str(runs_dir), "watch", run_id, "--jsonl", "--from", "0"])
        assert r.returncode == 0
        lines = [l for l in r.stdout.strip().split("\n") if l]
        assert len(lines) >= 1
        first = json.loads(lines[0])
        assert "event_id" in first

    def test_resume_nonterminal_run(self, tmp_path):
        path = tmp_path / "plan.json"
        path.write_text(json.dumps(_good_plan()))
        runs_dir = tmp_path / "runs"
        _run_cli(["--runs-dir", str(runs_dir), "run", str(path)])
        run_id = list(runs_dir.iterdir())[0].name
        r = _run_cli(["--runs-dir", str(runs_dir), "resume", run_id])
        assert r.returncode == 0

    def test_resume_unknown_run_fails(self, tmp_path):
        r = _run_cli(["--runs-dir", str(tmp_path / "runs"), "resume", "nonexistent"])
        assert r.returncode == 4

    def test_status_unknown_run_fails(self, tmp_path):
        r = _run_cli(["--runs-dir", str(tmp_path / "runs"), "status", "nonexistent"])
        assert r.returncode == 4

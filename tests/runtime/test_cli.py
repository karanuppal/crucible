"""Phase 8 tests: Crucible CLI."""

import json
import os
import io
import sys
import pytest

from crucible.runtime.cli import build_parser, main


def _good_plan_json(tmp_path):
    plan = {
        "spec": "build a thing",
        "project_id": "p1",
        "build_id": "b1",
        "tasks": [
            {
                "task_id": "implement-foo",
                "description": "implement src/foo.py with tests in tests/test_foo.py",
                "criteria": [{
                    "criterion_id": "c1",
                    "criterion_class": "must_pass",
                    "triple": {
                        "build_target": "src/foo.py",
                        "verification_command": "pytest tests/test_foo.py",
                        "expected_output": "PASSED",
                        "failure_signature": "FAILED",
                    },
                }],
                "role": "builder",
                "intensity_hint": "S",
            }
        ],
    }
    path = tmp_path / "plan.json"
    path.write_text(json.dumps(plan))
    return str(path)


def _bad_plan_json(tmp_path):
    plan = {"spec": "x", "project_id": "p1", "build_id": "b1", "tasks": []}
    path = tmp_path / "bad.json"
    path.write_text(json.dumps(plan))
    return str(path)


class TestLintPlan:
    def test_valid_plan_exits_zero(self, tmp_path):
        plan_path = _good_plan_json(tmp_path)
        rc = main(["lint-plan", plan_path])
        assert rc == 0
    
    def test_invalid_plan_exits_two(self, tmp_path):
        plan_path = _bad_plan_json(tmp_path)
        rc = main(["lint-plan", plan_path])
        assert rc == 2
    
    def test_missing_file_exits_one(self):
        rc = main(["lint-plan", "/nonexistent/plan.json"])
        assert rc == 1


class TestRun:
    def test_valid_plan_starts_run(self, tmp_path, capsys):
        plan_path = _good_plan_json(tmp_path)
        runs_dir = str(tmp_path / "runs")
        rc = main(["--runs-dir", runs_dir, "run", plan_path])
        assert rc == 0
        # A run dir was created
        assert os.path.isdir(runs_dir)
        run_dirs = os.listdir(runs_dir)
        assert len(run_dirs) == 1
        assert run_dirs[0].startswith("run-")
    
    def test_invalid_plan_blocks_run(self, tmp_path):
        plan_path = _bad_plan_json(tmp_path)
        rc = main(["--runs-dir", str(tmp_path / "runs"), "run", plan_path])
        assert rc == 2
    
    def test_jsonl_mode(self, tmp_path, capsys):
        plan_path = _good_plan_json(tmp_path)
        rc = main(["--runs-dir", str(tmp_path / "runs"), "run", plan_path, "--jsonl"])
        captured = capsys.readouterr()
        assert rc == 0
        # First line should be valid JSON
        first_line = captured.out.strip().split("\n")[0]
        parsed = json.loads(first_line)
        assert parsed["event"] == "run_started"
        assert "run_id" in parsed


class TestStatus:
    def test_unknown_run_id_exits_four(self, tmp_path):
        rc = main(["--runs-dir", str(tmp_path / "runs"), "status", "nonexistent"])
        assert rc == 4
    
    def test_status_for_running_run(self, tmp_path, capsys):
        plan_path = _good_plan_json(tmp_path)
        runs_dir = str(tmp_path / "runs")
        main(["--runs-dir", runs_dir, "run", plan_path])
        
        run_id = os.listdir(runs_dir)[0]
        rc = main(["--runs-dir", runs_dir, "status", run_id])
        assert rc == 0
        out = capsys.readouterr().out
        assert run_id in out


class TestWatch:
    def test_unknown_run_exits_four(self, tmp_path):
        rc = main(["--runs-dir", str(tmp_path / "runs"), "watch", "nonexistent"])
        assert rc == 4
    
    def test_watch_jsonl_emits_events(self, tmp_path, capsys):
        plan_path = _good_plan_json(tmp_path)
        runs_dir = str(tmp_path / "runs")
        main(["--runs-dir", runs_dir, "run", plan_path])
        run_id = os.listdir(runs_dir)[0]
        capsys.readouterr()  # clear prior output
        
        rc = main(["--runs-dir", runs_dir, "watch", run_id, "--jsonl", "--from", "0"])
        assert rc == 0
        out = capsys.readouterr().out
        # At least one JSON line
        lines = [l for l in out.strip().split("\n") if l]
        assert len(lines) >= 1
        first = json.loads(lines[0])
        assert "event_id" in first


class TestResume:
    def test_unknown_run_exits_four(self, tmp_path):
        rc = main(["--runs-dir", str(tmp_path / "runs"), "resume", "nonexistent"])
        assert rc == 4
    
    def test_resume_running_run(self, tmp_path):
        plan_path = _good_plan_json(tmp_path)
        runs_dir = str(tmp_path / "runs")
        main(["--runs-dir", runs_dir, "run", plan_path])
        run_id = os.listdir(runs_dir)[0]
        
        rc = main(["--runs-dir", runs_dir, "resume", run_id])
        assert rc == 0

"""Round-2 fix: openclaw_tool.py must be a structured machine interface."""

import json
import os
import pytest

from crucible.runtime.openclaw_tool import execute, TOOL_SCHEMA


def _good_plan():
    return {
        "spec": "openclaw tool wrapper test",
        "project_id": "tool-test",
        "build_id": "b1",
        "tasks": [
            {
                "task_id": "t1",
                "description": "verify src/foo.py with tests/test_foo.py",
                "criteria": [{
                    "criterion_id": "c1",
                    "criterion_class": "must_pass",
                    "triple": {
                        "build_target": "non-path-target",
                        "verification_command": "echo PASSED_OK",
                        "expected_output": "PASSED_OK",
                    },
                }],
                "role": "builder",
                "intensity_hint": "S",
            }
        ],
    }


def _bad_plan():
    return {"spec": "x", "project_id": "p", "build_id": "b", "tasks": []}


class TestSchemaContract:
    def test_tool_schema_present(self):
        assert TOOL_SCHEMA["name"] == "crucible"
        assert "input_schema" in TOOL_SCHEMA
        assert "mode" in TOOL_SCHEMA["input_schema"]["required"]
    
    def test_unknown_mode_returns_structured_error(self):
        out = execute({"mode": "fly-to-the-moon"})
        assert out["status"] == "error"
        assert "unknown mode" in out["message"]
    
    def test_non_dict_input_returns_error(self):
        out = execute("hello")  # type: ignore
        assert out["status"] == "error"


class TestLintMode:
    def test_lint_returns_structured_findings(self, tmp_path):
        out = execute({
            "mode": "lint",
            "plan": _bad_plan(),
            "runs_dir": str(tmp_path / "runs"),
        })
        assert out["status"] == "lint_failed"
        assert out["exit_code"] == 2
        assert isinstance(out.get("findings"), list)
    
    def test_lint_valid_plan_returns_ok(self, tmp_path):
        out = execute({
            "mode": "lint",
            "plan": _good_plan(),
            "runs_dir": str(tmp_path / "runs"),
        })
        assert out["status"] == "ok"
        assert out["exit_code"] == 0
        assert out["valid"] is True
    
    def test_lint_missing_plan_returns_error(self):
        out = execute({"mode": "lint"})
        assert out["status"] == "error"


class TestRunMode:
    def test_run_returns_run_id_and_run_root(self, tmp_path):
        out = execute({
            "mode": "run",
            "plan": _good_plan(),
            "runs_dir": str(tmp_path / "runs"),
        })
        assert out["status"] == "ok", f"got {out}"
        assert "run_id" in out, f"missing run_id: {out}"
        assert "run_root" in out
        assert out["run_id"].startswith("run-")
    
    def test_run_returns_terminal_status(self, tmp_path):
        out = execute({
            "mode": "run",
            "plan": _good_plan(),
            "runs_dir": str(tmp_path / "runs"),
        })
        assert out["terminal_status"] == "complete"
        assert "t1" in out["completed_tasks"]
    
    def test_run_failing_returns_terminal_failed(self, tmp_path):
        plan = _good_plan()
        plan["tasks"][0]["criteria"][0]["triple"]["verification_command"] = "false"
        out = execute({
            "mode": "run",
            "plan": plan,
            "runs_dir": str(tmp_path / "runs"),
        })
        assert out["status"] == "terminal"
        assert out["terminal_status"] == "failed"
    
    def test_run_lint_failed_propagates(self, tmp_path):
        out = execute({
            "mode": "run",
            "plan": _bad_plan(),
            "runs_dir": str(tmp_path / "runs"),
        })
        assert out["status"] == "lint_failed"
    
    def test_embedding_session_ref_threaded_into_manifest(self, tmp_path):
        out = execute({
            "mode": "run",
            "plan": _good_plan(),
            "runs_dir": str(tmp_path / "runs"),
            "embedding_surface": "openclaw-test",
            "embedding_session_ref": "session-abc-123",
        })
        assert "run_id" in out
        # Read the manifest from disk and verify the session ref made it
        manifest_path = os.path.join(out["run_root"], "run.json")
        manifest = json.loads(open(manifest_path).read())
        assert manifest["embedding_surface"] == "openclaw-test"
        assert manifest["embedding_session_ref"] == "session-abc-123"


class TestStatusMode:
    def test_status_returns_structured(self, tmp_path):
        runs_dir = str(tmp_path / "runs")
        run_out = execute({"mode": "run", "plan": _good_plan(), "runs_dir": runs_dir})
        run_id = run_out["run_id"]
        
        out = execute({"mode": "status", "run_id": run_id, "runs_dir": runs_dir})
        assert out["status"] == "ok"
        assert out["run_id"] == run_id
        assert out["phase"] == "done"
        assert out["is_terminal"] is True
        assert out["terminal_status"] == "complete"
    
    def test_status_unknown_returns_error(self, tmp_path):
        out = execute({
            "mode": "status",
            "run_id": "ghost",
            "runs_dir": str(tmp_path / "runs"),
        })
        assert out["status"] == "error"
        assert out["exit_code"] == 4
    
    def test_status_missing_run_id_returns_error(self):
        out = execute({"mode": "status"})
        assert out["status"] == "error"


class TestWatchMode:
    def test_watch_returns_event_list(self, tmp_path):
        runs_dir = str(tmp_path / "runs")
        run_out = execute({"mode": "run", "plan": _good_plan(), "runs_dir": runs_dir})
        run_id = run_out["run_id"]
        
        out = execute({"mode": "watch", "run_id": run_id, "runs_dir": runs_dir})
        assert isinstance(out["events"], list)
        assert len(out["events"]) > 0
        # Each event has event_id and type
        assert "event_id" in out["events"][0]
        assert "type" in out["events"][0]
    
    def test_watch_unknown_returns_error(self, tmp_path):
        out = execute({
            "mode": "watch",
            "run_id": "ghost",
            "runs_dir": str(tmp_path / "runs"),
        })
        assert out["exit_code"] == 4


class TestResumeMode:
    def test_resume_terminal_run_returns_status(self, tmp_path):
        runs_dir = str(tmp_path / "runs")
        run_out = execute({"mode": "run", "plan": _good_plan(), "runs_dir": runs_dir})
        run_id = run_out["run_id"]
        
        out = execute({"mode": "resume", "run_id": run_id, "runs_dir": runs_dir})
        assert out["status"] == "ok"
        assert out["terminal_status"] == "complete"
    
    def test_resume_returns_run_root(self, tmp_path):
        """Round-8 contract: resume must return run_root just like run does."""
        runs_dir = str(tmp_path / "runs")
        workspace_root = str(tmp_path / "workspace")
        os.makedirs(workspace_root, exist_ok=True)
        run_out = execute({
            "mode": "run",
            "plan": _good_plan(),
            "runs_dir": runs_dir,
            "workspace_root": workspace_root,
            "embedding_surface": "openclaw-test",
            "embedding_session_ref": "session-abc-123",
        })
        run_id = run_out["run_id"]
        original_run_root = run_out["run_root"]
        
        out = execute({"mode": "resume", "run_id": run_id, "runs_dir": runs_dir})
        assert "run_root" in out, f"resume missing run_root: {out}"
        assert out["run_root"] == original_run_root
        assert out["workspace_root"] == os.path.realpath(workspace_root)
        assert out["embedding_session_ref"] == "session-abc-123"
    
    def test_resume_unknown_returns_error(self, tmp_path):
        out = execute({
            "mode": "resume",
            "run_id": "ghost",
            "runs_dir": str(tmp_path / "runs"),
        })
        assert out["exit_code"] == 4

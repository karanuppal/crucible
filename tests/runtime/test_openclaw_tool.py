"""Round-2 fix: openclaw_tool.py must be a structured machine interface."""

import json
import os
import time
import pytest

from crucible.planning import PlanningError
from crucible.runtime.preflight import lint_plan
from crucible.runtime.run_store import create_run_store

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
        assert out["plan_status"] == "validated"
        assert out["plan"]["tasks"][0]["review_policy"]["tier"] == "standard"
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
        assert out["plan_present"] is True
        assert out["plan_status"] == "validated"
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
        assert out["plan_present"] is True
        assert out["plan_status"] == "validated"
        assert out["plan"]["run_id"] == run_id
        assert out["events"][0]["event"] == "plan_state"
        assert any("event_id" in event and "type" in event for event in out["events"][1:])
        assert any(event.get("type") == "plan_validated" for event in out["events"][1:])
    
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
        assert out["plan_status"] == "validated"
        assert out["terminal_status"] == "complete"
    
    def test_run_can_use_openclaw_bridge_backend(self, tmp_path):
        runs_dir = str(tmp_path / "runs")
        spawn_calls: list[str] = []
        wait_calls: list[str] = []

        def fake_spawn(prompt, spec_id, cwd, timeout_seconds, metadata):
            spawn_calls.append(spec_id)
            return f"oc-session-{spec_id}"

        def fake_wait(session_id, timeout):
            wait_calls.append(session_id)
            return {
                "status": "complete",
                "artifact_paths": ["src/built.py"],
                "summary": "bridge path complete",
            }

        out = execute({
            "mode": "run",
            "plan": _good_plan(),
            "runs_dir": runs_dir,
            "openclaw_spawn_callable": fake_spawn,
            "openclaw_wait_callable": fake_wait,
        })

        assert out["status"] == "ok", f"got {out}"
        assert out["terminal_status"] == "complete"
        assert spawn_calls == ["t1.c1"]
        assert wait_calls == ["oc-session-t1.c1"]

        adapter_log = open(os.path.join(out["run_root"], "adapter.log")).read()
        assert "openclaw-bridge" in adapter_log or "openclaw-subagent" in adapter_log

    def test_detach_can_use_openclaw_bridge_backend(self, tmp_path):
        runs_dir = str(tmp_path / "runs")
        spawn_calls: list[str] = []
        wait_calls: list[str] = []

        def fake_spawn(prompt, spec_id, cwd, timeout_seconds, metadata):
            spawn_calls.append(spec_id)
            return f"oc-session-{spec_id}"

        def fake_wait(session_id, timeout):
            wait_calls.append(session_id)
            time.sleep(0.05)
            return {
                "status": "complete",
                "artifact_paths": ["src/built.py"],
                "summary": "bridge detach complete",
            }

        out = execute({
            "mode": "run",
            "plan": _good_plan(),
            "runs_dir": runs_dir,
            "detach": True,
            "openclaw_spawn_callable": fake_spawn,
            "openclaw_wait_callable": fake_wait,
        })

        assert out["status"] == "ok", f"got {out}"
        assert out["exit_code"] == 0
        assert "run_id" in out and "run_root" in out

        result_path = os.path.join(out["run_root"], "result.json")
        for _ in range(50):
            if os.path.isfile(result_path):
                break
            time.sleep(0.02)

        assert os.path.isfile(result_path), "detached bridge-backed run never completed"
        result = json.loads(open(result_path).read())
        assert result["terminal_status"] == "complete"
        assert spawn_calls == ["t1.c1"]
        assert wait_calls == ["oc-session-t1.c1"]

    def test_resume_can_use_openclaw_bridge_backend(self, tmp_path):
        runs_dir = str(tmp_path / "runs")
        normalized = lint_plan(_good_plan()).normalized_plan or _good_plan()
        store, manifest = create_run_store(
            run_id=None,
            project_id=normalized["project_id"],
            build_id=normalized["build_id"],
            spec_text=normalized.get("spec", ""),
            task_plan=normalized,
            runs_root=runs_dir,
            workspace_root=str(tmp_path / "workspace"),
        )

        spawn_calls: list[str] = []
        wait_calls: list[str] = []

        def fake_spawn(prompt, spec_id, cwd, timeout_seconds, metadata):
            spawn_calls.append(spec_id)
            return f"oc-session-{spec_id}"

        def fake_wait(session_id, timeout):
            wait_calls.append(session_id)
            return {"status": "complete", "summary": "resume via bridge"}

        out = execute({
            "mode": "resume",
            "run_id": manifest.run_id,
            "runs_dir": runs_dir,
            "openclaw_spawn_callable": fake_spawn,
            "openclaw_wait_callable": fake_wait,
        })

        assert out["status"] == "ok", f"got {out}"
        assert out["terminal_status"] == "complete"
        assert spawn_calls == ["t1.c1"]
        assert wait_calls == ["oc-session-t1.c1"]
        assert out["run_root"] == manifest.run_root

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

    def test_resume_rejects_missing_durable_plan(self, tmp_path):
        runs_dir = str(tmp_path / "runs")
        run_out = execute({"mode": "run", "plan": _good_plan(), "runs_dir": runs_dir})
        run_root = run_out["run_root"]
        os.unlink(os.path.join(run_root, "result.json"))
        os.unlink(os.path.join(run_root, "plan.json"))

        out = execute({"mode": "resume", "run_id": run_out["run_id"], "runs_dir": runs_dir})
        assert out["status"] == "error"
        assert out["exit_code"] == 5
        assert "durable plan.json" in out["message"]

    def test_run_store_does_not_silently_swallow_plan_creation_failures(self, tmp_path, monkeypatch):
        def boom(**kwargs):
            raise RuntimeError("synthetic planning failure")

        monkeypatch.setattr("crucible.planning.build_plan_artifact", boom)
        with pytest.raises(RuntimeError, match="synthetic planning failure"):
            create_run_store(
                run_id=None,
                project_id="p1",
                build_id="b1",
                spec_text="spec",
                task_plan=_good_plan(),
                runs_root=str(tmp_path / "runs"),
            )

import os

from crucible.runtime.statuses import RunTerminalStatus
from crucible.runtime import (
    TOOL_SCHEMA,
    openclaw_resume,
    openclaw_run,
    openclaw_status,
    openclaw_watch,
)


def _good_plan():
    return {
        "spec": "phase 5 openclaw front-door test",
        "project_id": "phase5-openclaw",
        "build_id": "b1",
        "tasks": [
            {
                "task_id": "t1",
                "description": "verify front-door consistency",
                "criteria": [{
                    "criterion_id": "c1",
                    "criterion_class": "must_pass",
                    "triple": {
                        "build_target": "non-path-target",
                        "verification_command": "echo PHASE5_OK",
                        "expected_output": "PHASE5_OK",
                    },
                }],
                "role": "builder",
                "intensity_hint": "S",
            }
        ],
    }


class TestStableRuntimeEmbeddingApi:
    def test_runtime_exports_openclaw_helpers(self):
        assert TOOL_SCHEMA["name"] == "crucible"
        assert TOOL_SCHEMA["input_schema"]["properties"]["mode"]["enum"] == ["run", "lint", "status", "watch", "resume"]

    def test_same_run_maps_to_same_durable_semantics_across_surfaces(self, tmp_path):
        runs_dir = str(tmp_path / "runs")
        workspace_root = str(tmp_path / "workspace")
        os.makedirs(workspace_root, exist_ok=True)

        run_out = openclaw_run({
            "plan": _good_plan(),
            "runs_dir": runs_dir,
            "workspace_root": workspace_root,
            "embedding_surface": "telegram-topic",
            "embedding_session_ref": "topic-6442",
        })
        run_id = run_out["run_id"]
        run_root = run_out["run_root"]

        status_out = openclaw_status({"run_id": run_id, "runs_dir": runs_dir})
        watch_out = openclaw_watch({"run_id": run_id, "runs_dir": runs_dir})
        resume_out = openclaw_resume({"run_id": run_id, "runs_dir": runs_dir})

        for out in (run_out, status_out, watch_out, resume_out):
            assert out["plan_status"] == "validated", out

        assert run_out["terminal_status"] == RunTerminalStatus.SUCCEEDED.value
        assert status_out["terminal_status"] == RunTerminalStatus.SUCCEEDED.value
        assert resume_out["terminal_status"] == RunTerminalStatus.SUCCEEDED.value

        assert run_out["run_id"] == status_out["run_id"] == watch_out["run_id"] == resume_out["run_id"] == run_id
        assert resume_out["run_root"] == run_root
        assert resume_out["workspace_root"] == os.path.realpath(workspace_root)
        assert resume_out["embedding_session_ref"] == "topic-6442"
        assert status_out["plan"]["run_id"] == run_id
        assert watch_out["plan"]["run_id"] == run_id
        assert watch_out["events"][0]["event"] == "plan_state"

    def test_same_run_is_inspectable_even_when_openclaw_surface_name_differs(self, tmp_path):
        runs_dir = str(tmp_path / "runs")
        run_out = openclaw_run({
            "plan": _good_plan(),
            "runs_dir": runs_dir,
            "embedding_surface": "openclaw-mobile",
            "embedding_session_ref": "session-mobile-1",
        })

        status_from_other_surface = openclaw_status({
            "run_id": run_out["run_id"],
            "runs_dir": runs_dir,
            "embedding_surface": "openclaw-desktop",
        })
        resume_from_other_surface = openclaw_resume({
            "run_id": run_out["run_id"],
            "runs_dir": runs_dir,
            "embedding_surface": "openclaw-desktop",
        })

        assert status_from_other_surface["run_id"] == run_out["run_id"]
        assert status_from_other_surface["terminal_status"] == RunTerminalStatus.SUCCEEDED.value
        assert status_from_other_surface["plan"]["source"]["embedding_surface"] == "openclaw-mobile"
        assert resume_from_other_surface["embedding_session_ref"] == "session-mobile-1"
        assert resume_from_other_surface["run_root"] == run_out["run_root"]

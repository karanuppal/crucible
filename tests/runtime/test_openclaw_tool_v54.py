from crucible.runtime.openclaw_tool import execute


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


def test_run_and_status_expose_semantic_state(tmp_path):
    runs_dir = str(tmp_path / "runs")
    out = execute({"mode": "run", "plan": _good_plan(), "runs_dir": runs_dir})
    assert out["semantic_state"] == "complete"
    status = execute({"mode": "status", "run_id": out["run_id"], "runs_dir": runs_dir})
    assert status["semantic_state"] == "complete"

"""G2: The harness MUST execute verification commands and report honestly.

This is the test pack the reviewer used to break us. If any test here
ever regresses, Phase 8 is broken.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from crucible.accelerators.adapters import AdapterRunHandle, AdapterRunResult, AdapterRunSpec, AdapterStatus, BackendAdapter
from crucible.accelerators.capabilities import BackendCapabilities, Capability
from crucible.runtime.preflight import lint_plan
from crucible.runtime.run_executor import execute_run
from crucible.runtime.run_store import create_run_store
from crucible.runtime.statuses import RunTerminalStatus, TaskTerminalStatus


CLI = [sys.executable, "-m", "crucible.runtime.cli"]


def _run(args, timeout=30, cwd=None):
    return subprocess.run(CLI + args, capture_output=True, text=True, timeout=timeout, cwd=cwd)


def _ensure_target(workspace, target):
    """Create the build_target file inside workspace so the executor's
    target-existence check passes."""
    full = os.path.join(workspace, target)
    os.makedirs(os.path.dirname(full), exist_ok=True)
    with open(full, "w") as f:
        f.write("# stub for tests\n")


def _plan(*, command, expected, build_target="src/foo.py"):
    return {
        "spec": "verification truth test",
        "project_id": "truth-test",
        "build_id": "b1",
        "tasks": [
            {
                "task_id": "verify-task",
                "description": "verify the criterion runs honestly src/foo.py tests/test_foo.py",
                "criteria": [
                    {
                        "criterion_id": "c1",
                        "criterion_class": "must_pass",
                        "triple": {
                            "build_target": build_target,
                            "verification_command": command,
                            "expected_output": expected,
                        },
                    }
                ],
                "role": "builder",
                "intensity_hint": "S",
            }
        ],
    }


def _write(tmp_path, plan):
    p = tmp_path / "plan.json"
    p.write_text(json.dumps(plan))
    return str(p)


class _AlwaysFailingAdapter(BackendAdapter):
    def __init__(self):
        self._caps = BackendCapabilities(
            backend_id="always-fail",
            supports={Capability.SHELL_EXEC, Capability.FILE_WRITE},
            max_concurrent_runs=1,
        )
        self._runs = {}

    def backend_id(self) -> str:
        return "always-fail"

    def declared_capabilities(self) -> BackendCapabilities:
        return self._caps

    def spawn(self, spec: AdapterRunSpec) -> AdapterRunHandle:
        target = Path(spec.cwd) / "src" / "foo.py"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("# still broken\n")
        handle = AdapterRunHandle(handle_id=f"h-{spec.spec_id}", backend_id=self.backend_id(), spawned_at=0.0, spec_id=spec.spec_id)
        self._runs[handle.handle_id] = AdapterRunResult(
            handle_id=handle.handle_id,
            status=AdapterStatus.FAILED,
            error="still failing",
            artifact_paths=[str(target)],
        )
        return handle

    def poll(self, handle: AdapterRunHandle) -> AdapterStatus:
        return self._runs[handle.handle_id].status

    def collect(self, handle: AdapterRunHandle) -> AdapterRunResult:
        return self._runs[handle.handle_id]

    def kill(self, handle: AdapterRunHandle) -> None:
        return None


class TestValidationTruth:
    def test_failing_command_fails_task(self, tmp_path):
        plan = _plan(command="false", expected="WHATEVER")
        path = _write(tmp_path, plan)
        r = _run(["--runs-dir", str(tmp_path / "runs"), "run", path])
        assert r.returncode == 3, f"expected exit 3, got {r.returncode}\n{r.stdout}\n{r.stderr}"
        assert "terminal_status: run_failed" in r.stdout
    
    def test_wrong_expected_output_fails_task(self, tmp_path):
        plan = _plan(command="echo BAR", expected="FOO_NOT_PRESENT")
        path = _write(tmp_path, plan)
        r = _run(["--runs-dir", str(tmp_path / "runs"), "run", path])
        assert r.returncode == 3
        assert "failed" in r.stdout.lower()
    
    def test_nonexistent_command_fails_task(self, tmp_path):
        """The reviewer's killer test."""
        plan = _plan(command="this-command-does-not-exist-12345", expected="ANYTHING")
        path = _write(tmp_path, plan)
        r = _run(["--runs-dir", str(tmp_path / "runs"), "run", path])
        assert r.returncode == 3, f"got {r.returncode}: {r.stdout}"
        assert "terminal_status: run_blocked" in r.stdout
    
    def test_passing_command_passes_task(self, tmp_path):
        plan = _plan(command="echo 'all tests PASSED here'", expected="PASSED")
        path = _write(tmp_path, plan)
        # Create the build_target file so the existence check passes
        _ensure_target(str(tmp_path), "src/foo.py")
        r = _run(["--runs-dir", str(tmp_path / "runs"), "run", path,
                  "--workspace-root", str(tmp_path)])
        assert r.returncode == 0, f"got {r.returncode}: {r.stdout}\n{r.stderr}"
        assert "terminal_status: run_succeeded" in r.stdout
    
    def test_partial_pass_marks_partial(self, tmp_path):
        # Two tasks: one passes, one fails
        plan = {
            "spec": "mixed pass-fail test",
            "project_id": "mixed",
            "build_id": "b1",
            "tasks": [
                {
                    "task_id": "good-one",
                    "description": "verify src/good.py with tests/test_good.py",
                    "criteria": [{
                        "criterion_id": "c1",
                        "criterion_class": "must_pass",
                        "triple": {
                            "build_target": "src/good.py",
                            "verification_command": "echo PASSED_OK",
                            "expected_output": "PASSED_OK",
                        },
                    }],
                    "role": "builder",
                    "intensity_hint": "S",
                },
                {
                    "task_id": "bad-one",
                    "description": "verify src/bad.py with tests/test_bad.py",
                    "criteria": [{
                        "criterion_id": "c1",
                        "criterion_class": "must_pass",
                        "triple": {
                            "build_target": "src/bad.py",
                            "verification_command": "false",
                            "expected_output": "NEVER_HAPPENS",
                        },
                    }],
                    "role": "builder",
                    "intensity_hint": "S",
                },
            ],
        }
        path = _write(tmp_path, plan)
        _ensure_target(str(tmp_path), "src/good.py")
        _ensure_target(str(tmp_path), "src/bad.py")
        r = _run(["--runs-dir", str(tmp_path / "runs"), "run", path,
                  "--workspace-root", str(tmp_path)])
        assert r.returncode == 3
        assert "run_failed" in r.stdout
        # Verify the result.json says the canonical failed run status
        runs_dir = tmp_path / "runs"
        run_dir = list(runs_dir.iterdir())[0]
        result = json.loads((run_dir / "result.json").read_text())
        assert result["terminal_status"] == "run_failed"
        assert "good-one" in result["completed_tasks"]
        assert "bad-one" in result["failed_tasks"]
    
    def test_event_stream_records_criterion_outcomes(self, tmp_path):
        plan = _plan(command="echo PASSED_HERE", expected="PASSED_HERE")
        path = _write(tmp_path, plan)
        _ensure_target(str(tmp_path), "src/foo.py")
        _run(["--runs-dir", str(tmp_path / "runs"), "run", path,
              "--workspace-root", str(tmp_path)])
        run_dir = list((tmp_path / "runs").iterdir())[0]
        events = (run_dir / "events.jsonl").read_text().strip().split("\n")
        types = [json.loads(e)["type"] for e in events if e]
        assert "criterion_dispatched" in types
        assert "criterion_passed" in types
        assert "task_completed" in types
    
    def test_semantic_bypass_blocked(self, tmp_path):
        """Round-2 reviewer's killer test: passing command + nonexistent target → fail.
        
        echo PASS_OK exits 0 and prints PASS_OK, but build_target src/nonexistent.py
        does not exist on disk. The harness MUST NOT mark this complete.
        """
        plan = _plan(
            command="echo PASS_OK",
            expected="PASS_OK",
            build_target="src/nonexistent_target.py",
        )
        path = _write(tmp_path, plan)
        # Deliberately do NOT create the target file
        r = _run(["--runs-dir", str(tmp_path / "runs"), "run", path,
                  "--workspace-root", str(tmp_path)])
        assert r.returncode == 3, (
            f"semantic bypass not blocked: exit={r.returncode}\nstdout: {r.stdout}\nstderr: {r.stderr}"
        )
        assert "terminal_status: run_failed" in r.stdout
    
    def test_existing_target_with_passing_command_passes(self, tmp_path):
        """Sanity: if the build_target really exists, a real pass should still pass."""
        plan = _plan(command="echo PASSED_OK", expected="PASSED_OK", build_target="src/realfile.py")
        path = _write(tmp_path, plan)
        _ensure_target(str(tmp_path), "src/realfile.py")
        r = _run(["--runs-dir", str(tmp_path / "runs"), "run", path,
                  "--workspace-root", str(tmp_path)])
        assert r.returncode == 0, f"got {r.returncode}\n{r.stdout}\n{r.stderr}"
    
    def test_failure_event_recorded(self, tmp_path):
        plan = _plan(command="false", expected="NEVER_GONNA_HAPPEN")
        path = _write(tmp_path, plan)
        _run(["--runs-dir", str(tmp_path / "runs"), "run", path])
        run_dir = list((tmp_path / "runs").iterdir())[0]
        events = (run_dir / "events.jsonl").read_text().strip().split("\n")
        types = [json.loads(e)["type"] for e in events if e]
        assert "criterion_failed" in types
        assert "task_failed" in types

    def test_task_failed_semantics_do_not_collapse_to_run_blocked(self, tmp_path):
        plan = lint_plan(_plan(command="true", expected="OK_OK")).normalized_plan
        store, manifest = create_run_store(
            run_id=None,
            project_id=plan["project_id"],
            build_id=plan["build_id"],
            spec_text=plan.get("spec", ""),
            task_plan=plan,
            runs_root=str(tmp_path / "runs"),
            workspace_root=str(tmp_path / "seed"),
        )
        (tmp_path / "seed" / "src").mkdir(parents=True)

        summary = execute_run(
            store=store,
            manifest=manifest,
            plan=plan,
            adapter_factory=lambda s: [_AlwaysFailingAdapter()],
            workspace_root=str(tmp_path / "seed"),
        )

        assert summary.terminal_status == RunTerminalStatus.FAILED.value
        events = [json.loads(line) for line in Path(store.events_path).read_text().splitlines() if line.strip()]
        semantic_states = [
            event["payload"].get("semantic_state")
            for event in events
            if event["type"] in {"task_failed", "task_blocked"}
        ]
        assert TaskTerminalStatus.FAILED.value in semantic_states
        assert TaskTerminalStatus.BLOCKED.value not in semantic_states

"""Round-2 fix: BridgeBackedAdapter must work inside execute_run().

The round-2 reviewer's blocker: the bridge existed but execute_run()
couldn't actually use it because BackendAdapter.spawn()+collect() doesn't
include a wait step. BridgeBackedAdapter wraps the bridge so the executor
sees a normal sync adapter.
"""

import pytest

from crucible.accelerators.adapters import AdapterStatus
from crucible.runtime.statuses import RunTerminalStatus
from crucible.runtime.openclaw_bridge import (
    SimulatedOpenClawBridge, SessionsSpawnBridge, BridgeBackedAdapter,
)
from crucible.runtime.preflight import lint_plan
from crucible.runtime.run_executor import execute_run
from crucible.runtime.run_store import create_run_store


def _good_plan():
    return {
        "spec": "bridge integration test",
        "project_id": "bridge-int",
        "build_id": "b1",
        "tasks": [{
            "task_id": "t1",
            "description": "verify src/foo.py with tests/test_foo.py",
            "criteria": [{
                "criterion_id": "c1",
                "criterion_class": "must_pass",
                "triple": {
                    "build_target": "non-path-target",
                    "verification_command": "echo PASSED_VIA_BRIDGE",
                    "expected_output": "PASSED_VIA_BRIDGE",
                },
            }],
            "role": "builder",
            "intensity_hint": "S",
        }],
    }


def _store(tmp_path, plan):
    normalized = lint_plan(plan).normalized_plan or plan
    return create_run_store(
        run_id=None, project_id=normalized["project_id"], build_id=normalized["build_id"],
        spec_text=normalized.get("spec", ""), task_plan=normalized,
        runs_root=str(tmp_path / "runs"),
    )


class TestSimulatedBridgeInExecutor:
    def test_simulated_bridge_drives_run_to_complete(self, tmp_path):
        plan = _good_plan()
        store, manifest = _store(tmp_path, plan)
        
        def factory(s):
            bridge = SimulatedOpenClawBridge(
                s,
                outcome=AdapterStatus.COMPLETE,
                artifacts=["src/foo.py"],
            )
            return [BridgeBackedAdapter(bridge)]
        
        summary = execute_run(
            store=store, manifest=manifest, plan=plan,
            adapter_factory=factory,
        )
        assert summary.terminal_status == RunTerminalStatus.SUCCEEDED.value, f"got {summary.to_dict()}"
        assert "t1" in summary.completed_tasks
    
    def test_simulated_bridge_failed_outcome_marks_failed(self, tmp_path):
        plan = _good_plan()
        store, manifest = _store(tmp_path, plan)
        
        def factory(s):
            bridge = SimulatedOpenClawBridge(
                s,
                outcome=AdapterStatus.FAILED,
                error="sub-agent crashed",
            )
            return [BridgeBackedAdapter(bridge)]
        
        summary = execute_run(
            store=store, manifest=manifest, plan=plan,
            adapter_factory=factory,
        )
        assert summary.terminal_status == RunTerminalStatus.FAILED.value


class TestSessionsSpawnBridgeInExecutor:
    def test_full_sessions_spawn_path(self, tmp_path):
        """Simulate a real OpenClaw embedder providing spawn + wait callables."""
        plan = _good_plan()
        store, manifest = _store(tmp_path, plan)

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
                "summary": "build done",
            }

        def factory(s):
            bridge = SessionsSpawnBridge(
                s,
                spawn_callable=fake_spawn,
                wait_callable=fake_wait,
            )
            return [BridgeBackedAdapter(bridge)]

        summary = execute_run(
            store=store, manifest=manifest, plan=plan,
            adapter_factory=factory,
        )

        assert summary.terminal_status == RunTerminalStatus.SUCCEEDED.value
        assert len(spawn_calls) >= 1
        assert len(wait_calls) >= 1
        assert wait_calls[0].startswith("oc-session-")

    def test_sessions_spawn_failed_path(self, tmp_path):
        plan = _good_plan()
        store, manifest = _store(tmp_path, plan)

        def fake_spawn(prompt, spec_id, cwd, timeout_seconds, metadata):
            return f"oc-{spec_id}"

        def fake_wait(session_id, timeout):
            return {"status": "failed", "error": "tests blew up"}

        def factory(s):
            bridge = SessionsSpawnBridge(
                s,
                spawn_callable=fake_spawn,
                wait_callable=fake_wait,
            )
            return [BridgeBackedAdapter(bridge)]

        summary = execute_run(
            store=store, manifest=manifest, plan=plan,
            adapter_factory=factory,
        )
        assert summary.terminal_status == RunTerminalStatus.FAILED.value

    def test_spawn_exception_marks_run_failed(self, tmp_path):
        plan = _good_plan()
        store, manifest = _store(tmp_path, plan)

        def crashing_spawn(prompt, spec_id, cwd, timeout_seconds, metadata):
            raise RuntimeError("openclaw down")

        def fake_wait(session_id, timeout):
            return {"status": "complete"}

        def factory(s):
            bridge = SessionsSpawnBridge(
                s,
                spawn_callable=crashing_spawn,
                wait_callable=fake_wait,
            )
            return [BridgeBackedAdapter(bridge)]

        summary = execute_run(
            store=store, manifest=manifest, plan=plan,
            adapter_factory=factory,
        )
        assert summary.terminal_status == RunTerminalStatus.FAILED.value

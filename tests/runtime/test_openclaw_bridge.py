"""G4: OpenClaw bridge tests — both simulator and production shim paths."""

import pytest

from crucible.accelerators.adapters import AdapterRunSpec, AdapterStatus
from crucible.accelerators.capabilities import Capability
from crucible.runtime.run_store import create_run_store
from crucible.runtime.openclaw_bridge import (
    SimulatedOpenClawBridge, SessionsSpawnBridge, BridgeOutcome,
)


def _store(tmp_path):
    store, _ = create_run_store(
        run_id=None, project_id="bridge-test", build_id="b1",
        spec_text="x", task_plan={"spec": "x", "project_id": "bridge-test", "build_id": "b1", "tasks": []},
        runs_root=str(tmp_path / "runs"),
    )
    return store


def _spec(spec_id="s1"):
    return AdapterRunSpec(
        spec_id=spec_id,
        prompt="implement x",
        cwd="/tmp",
        timeout_seconds=30,
        required_capabilities={Capability.SHELL_EXEC, Capability.ARTIFACT_PRODUCTION},
    )


# ─────────────────────────────────────────────────────────────────
# Simulated bridge
# ─────────────────────────────────────────────────────────────────

class TestSimulatedBridge:
    def test_complete_outcome(self, tmp_path):
        store = _store(tmp_path)
        bridge = SimulatedOpenClawBridge(
            store,
            outcome=AdapterStatus.COMPLETE,
            artifacts=["src/foo.py", "tests/test_foo.py"],
        )
        outcome = bridge.run_spec_to_completion(_spec())
        assert outcome.status == AdapterStatus.COMPLETE
        assert "src/foo.py" in outcome.artifact_paths
        assert outcome.openclaw_session_id.startswith("sim-session-")
    
    def test_failed_outcome(self, tmp_path):
        store = _store(tmp_path)
        bridge = SimulatedOpenClawBridge(
            store,
            outcome=AdapterStatus.FAILED,
            error="sub-agent crashed",
        )
        outcome = bridge.run_spec_to_completion(_spec())
        assert outcome.status == AdapterStatus.FAILED
        assert "crashed" in outcome.error
    
    def test_partial_outcome(self, tmp_path):
        store = _store(tmp_path)
        bridge = SimulatedOpenClawBridge(
            store,
            outcome=AdapterStatus.PARTIAL,
            artifacts=["src/half.py"],
            error="incomplete tests",
        )
        outcome = bridge.run_spec_to_completion(_spec())
        assert outcome.status == AdapterStatus.PARTIAL
        assert "src/half.py" in outcome.artifact_paths
    
    def test_persists_state_for_collect_after_restart(self, tmp_path):
        store = _store(tmp_path)
        bridge = SimulatedOpenClawBridge(store)
        outcome = bridge.run_spec_to_completion(_spec())
        
        # State persists in run store
        state = store.read_adapter_state(outcome.handle_id)
        assert state is not None
        assert state["status"] == "complete"
        assert state["openclaw_session_id"]


# ─────────────────────────────────────────────────────────────────
# Production shim
# ─────────────────────────────────────────────────────────────────

class TestSessionsSpawnBridge:
    def test_spawn_and_wait_complete(self, tmp_path):
        store = _store(tmp_path)
        spawn_calls = []
        wait_calls = []
        
        def fake_spawn(prompt, spec_id, cwd, timeout_seconds, metadata):
            spawn_calls.append((prompt, spec_id))
            return f"oc-session-{spec_id}"
        
        def fake_wait(session_id, timeout):
            wait_calls.append((session_id, timeout))
            return {
                "status": "complete",
                "artifact_paths": ["src/x.py"],
                "summary": "done",
                "error": "",
            }
        
        bridge = SessionsSpawnBridge(
            store,
            spawn_callable=fake_spawn,
            wait_callable=fake_wait,
        )
        
        outcome = bridge.run_spec_to_completion(_spec("task-1"))
        
        assert len(spawn_calls) == 1
        assert spawn_calls[0][1] == "task-1"
        assert len(wait_calls) == 1
        assert wait_calls[0][0] == "oc-session-task-1"
        assert outcome.status == AdapterStatus.COMPLETE
        assert "src/x.py" in outcome.artifact_paths
    
    def test_spawn_failure_reported(self, tmp_path):
        store = _store(tmp_path)
        
        def crashing_spawn(prompt, spec_id, cwd, timeout_seconds, metadata):
            raise RuntimeError("openclaw down")
        
        def never_called_wait(session_id, timeout):
            pytest.fail("wait should not be called when spawn fails")
        
        bridge = SessionsSpawnBridge(
            store,
            spawn_callable=crashing_spawn,
            wait_callable=never_called_wait,
        )
        
        outcome = bridge.run_spec_to_completion(_spec())
        assert outcome.status == AdapterStatus.FAILED
        assert "openclaw down" in outcome.error
    
    def test_wait_callable_exception_marks_failed(self, tmp_path):
        store = _store(tmp_path)
        
        def fake_spawn(prompt, spec_id, cwd, timeout_seconds, metadata):
            return f"oc-session-{spec_id}"
        
        def crashing_wait(session_id, timeout):
            raise TimeoutError("openclaw never replied")
        
        bridge = SessionsSpawnBridge(
            store,
            spawn_callable=fake_spawn,
            wait_callable=crashing_wait,
        )
        
        outcome = bridge.run_spec_to_completion(_spec())
        assert outcome.status == AdapterStatus.FAILED
        assert "never replied" in outcome.error
    
    def test_wait_returns_failed_status(self, tmp_path):
        store = _store(tmp_path)
        
        def fake_spawn(prompt, spec_id, cwd, timeout_seconds, metadata):
            return f"oc-{spec_id}"
        
        def fake_wait(session_id, timeout):
            return {"status": "failed", "error": "tests did not pass"}
        
        bridge = SessionsSpawnBridge(
            store,
            spawn_callable=fake_spawn,
            wait_callable=fake_wait,
        )
        
        outcome = bridge.run_spec_to_completion(_spec())
        assert outcome.status == AdapterStatus.FAILED
        assert "tests did not pass" in outcome.error
    
    def test_state_persisted_for_restart_recovery(self, tmp_path):
        store = _store(tmp_path)
        
        def fake_spawn(prompt, spec_id, cwd, timeout_seconds, metadata):
            return f"oc-{spec_id}"
        
        def fake_wait(session_id, timeout):
            return {"status": "complete", "artifact_paths": ["a.py"]}
        
        bridge = SessionsSpawnBridge(
            store,
            spawn_callable=fake_spawn,
            wait_callable=fake_wait,
        )
        outcome = bridge.run_spec_to_completion(_spec())
        
        # Restart simulation: new bridge instance reads same store
        bridge2 = SessionsSpawnBridge(
            store,
            spawn_callable=fake_spawn,
            wait_callable=fake_wait,
        )
        state = store.read_adapter_state(outcome.handle_id)
        assert state["status"] == "complete"

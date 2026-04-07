"""Phase 8 tests: OpenClaw sub-agent adapter (event-backed sync facade)."""

import time
import pytest

from crucible.accelerators.adapters import (
    AdapterRunSpec, AdapterStatus,
)
from crucible.accelerators.capabilities import Capability
from crucible.runtime.run_store import create_run_store
from crucible.runtime.openclaw_adapter import (
    OpenClawSubagentAdapter, default_openclaw_capabilities,
)


def _make_store(tmp_path):
    store, _ = create_run_store(
        run_id=None, project_id="p1", build_id="b1",
        spec_text="x", task_plan={"spec": "x", "project_id": "p1", "build_id": "b1", "tasks": []},
        runs_root=str(tmp_path / "runs"),
    )
    return store


def _spec(spec_id="s1"):
    return AdapterRunSpec(
        spec_id=spec_id,
        prompt="implement x",
        cwd="/tmp",
        timeout_seconds=60,
        required_capabilities={Capability.SHELL_EXEC, Capability.ARTIFACT_PRODUCTION},
    )


class TestSpawnLifecycle:
    def test_spawn_persists_initial_state(self, tmp_path):
        store = _make_store(tmp_path)
        adapter = OpenClawSubagentAdapter(
            store, spawn_fn=lambda spec: f"oc-session-{spec.spec_id}"
        )
        
        handle = adapter.spawn(_spec("s1"))
        assert handle.backend_id == "openclaw-subagent"
        
        state = store.read_adapter_state(handle.handle_id)
        assert state is not None
        assert state["status"] == "running"
        assert state["openclaw_session_id"] == "oc-session-s1"
    
    def test_spawn_failure_persists_failed_state(self, tmp_path):
        store = _make_store(tmp_path)
        def boom(spec):
            raise RuntimeError("openclaw down")
        adapter = OpenClawSubagentAdapter(store, spawn_fn=boom)
        
        handle = adapter.spawn(_spec())
        state = store.read_adapter_state(handle.handle_id)
        assert state["status"] == "failed"
        assert "openclaw down" in state["error"]
    
    def test_missing_capability_rejected(self, tmp_path):
        store = _make_store(tmp_path)
        adapter = OpenClawSubagentAdapter(store, spawn_fn=lambda s: "oc-1")
        
        spec = AdapterRunSpec(
            spec_id="s1", prompt="x", cwd="/tmp", timeout_seconds=60,
            required_capabilities={Capability.MEMORY},
        ) if hasattr(Capability, "MEMORY") else None
        if spec is None:
            # Use an unsupported one — make it up by removing all caps
            adapter._caps.supports = set()
            spec = AdapterRunSpec(
                spec_id="s1", prompt="x", cwd="/tmp", timeout_seconds=60,
                required_capabilities={Capability.NETWORK},
            )
        with pytest.raises(ValueError, match="not support"):
            adapter.spawn(spec)


class TestEventIngestion:
    def test_ingest_terminal_complete(self, tmp_path):
        store = _make_store(tmp_path)
        adapter = OpenClawSubagentAdapter(store, spawn_fn=lambda s: "oc-1")
        handle = adapter.spawn(_spec())
        
        adapter.ingest_event(
            handle.handle_id,
            status=AdapterStatus.COMPLETE,
            artifact_paths=["src/foo.py", "tests/test_foo.py"],
            summary="ok",
        )
        
        result = adapter.collect(handle)
        assert result.status == AdapterStatus.COMPLETE
        assert "src/foo.py" in result.artifact_paths
        assert result.summary == "ok"
    
    def test_ingest_partial(self, tmp_path):
        store = _make_store(tmp_path)
        adapter = OpenClawSubagentAdapter(store, spawn_fn=lambda s: "oc-1")
        handle = adapter.spawn(_spec())
        
        adapter.ingest_event(
            handle.handle_id,
            status=AdapterStatus.PARTIAL,
            artifact_paths=["src/foo.py"],
            error="incomplete tests",
        )
        
        result = adapter.collect(handle)
        assert result.status == AdapterStatus.PARTIAL
        assert "src/foo.py" in result.artifact_paths
        assert result.error == "incomplete tests"
    
    def test_terminal_state_idempotent(self, tmp_path):
        store = _make_store(tmp_path)
        adapter = OpenClawSubagentAdapter(store, spawn_fn=lambda s: "oc-1")
        handle = adapter.spawn(_spec())
        
        adapter.ingest_event(handle.handle_id, status=AdapterStatus.COMPLETE)
        adapter.ingest_event(handle.handle_id, status=AdapterStatus.COMPLETE)
        # No exception, status stays terminal
        result = adapter.collect(handle)
        assert result.status == AdapterStatus.COMPLETE
    
    def test_unknown_handle_event_logged(self, tmp_path):
        store = _make_store(tmp_path)
        adapter = OpenClawSubagentAdapter(store, spawn_fn=lambda s: "oc-1")
        # Should not raise
        adapter.ingest_event("unknown-handle", status=AdapterStatus.COMPLETE)


class TestPollAndCollectFromPersistedState:
    def test_poll_reads_persisted_state(self, tmp_path):
        store = _make_store(tmp_path)
        adapter = OpenClawSubagentAdapter(store, spawn_fn=lambda s: "oc-1")
        handle = adapter.spawn(_spec())
        
        assert adapter.poll(handle) == AdapterStatus.RUNNING
        
        adapter.ingest_event(handle.handle_id, status=AdapterStatus.COMPLETE)
        assert adapter.poll(handle) == AdapterStatus.COMPLETE
    
    def test_collect_after_restart(self, tmp_path):
        """After process restart, a new adapter instance reads from persisted state."""
        store = _make_store(tmp_path)
        adapter1 = OpenClawSubagentAdapter(store, spawn_fn=lambda s: "oc-1")
        handle = adapter1.spawn(_spec())
        adapter1.ingest_event(handle.handle_id, status=AdapterStatus.COMPLETE,
                              artifact_paths=["x.py"], summary="done")
        
        # Simulate restart: new adapter instance, same store
        adapter2 = OpenClawSubagentAdapter(store, spawn_fn=lambda s: "oc-1")
        result = adapter2.collect(handle)
        assert result.status == AdapterStatus.COMPLETE
        assert "x.py" in result.artifact_paths


class TestKill:
    def test_kill_marks_killed(self, tmp_path):
        store = _make_store(tmp_path)
        adapter = OpenClawSubagentAdapter(store, spawn_fn=lambda s: "oc-1")
        handle = adapter.spawn(_spec())
        
        adapter.kill(handle)
        result = adapter.collect(handle)
        assert result.status == AdapterStatus.KILLED
    
    def test_kill_doesnt_overwrite_terminal(self, tmp_path):
        store = _make_store(tmp_path)
        adapter = OpenClawSubagentAdapter(store, spawn_fn=lambda s: "oc-1")
        handle = adapter.spawn(_spec())
        
        adapter.ingest_event(handle.handle_id, status=AdapterStatus.COMPLETE)
        adapter.kill(handle)
        
        result = adapter.collect(handle)
        assert result.status == AdapterStatus.COMPLETE  # not killed

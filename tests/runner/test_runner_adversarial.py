"""Phase 2 adversarial tests addressing all blocking findings."""

import json
import pytest
import time

from agentic_harness.runner.run_graph import RunGraph, RunStatus, RunRole
from agentic_harness.runner.circuit_breaker import CircuitBreaker
from agentic_harness.runner.spawn_controller import (
    SpawnController, SpawnConfig, SpawnResult,
)


# ─────────────────────────────────────────────────────────────────
# 1. Orphan prevention
# ─────────────────────────────────────────────────────────────────

class TestOrphanPrevention:
    def test_unknown_parent_rejected(self):
        g = RunGraph()
        with pytest.raises(ValueError, match="unknown parent"):
            g.spawn("t1", RunRole.BUILDER, parent_run_id="missing-parent")
    
    def test_task_owned_root_allowed(self):
        g = RunGraph()
        rid = g.spawn("t1", RunRole.BUILDER)  # no parent = task root
        assert rid in g._task_owned_roots
    
    def test_reattach_to_new_owner(self):
        g = RunGraph()
        owner_a = g.spawn("t1", RunRole.BUILDER)
        owner_b = g.spawn("t1", RunRole.INTEGRATOR)
        child = g.spawn("t1", RunRole.RESEARCHER, parent_run_id=owner_a)
        
        g.reattach_child(child, owner_b)
        
        node_a = g.get(owner_a)
        node_b = g.get(owner_b)
        assert child not in node_a.blocking_children
        assert child in node_b.blocking_children
        assert g.get(child).parent_run_id == owner_b
    
    def test_reattach_to_task_root(self):
        g = RunGraph()
        owner = g.spawn("t1", RunRole.BUILDER)
        child = g.spawn("t1", RunRole.RESEARCHER, parent_run_id=owner)
        
        g.reattach_child(child, None)
        
        assert g.get(child).parent_run_id == ""
        assert child in g._task_owned_roots


# ─────────────────────────────────────────────────────────────────
# 2. Cancellation propagation (automatic)
# ─────────────────────────────────────────────────────────────────

class TestCancellationPropagation:
    def test_killed_parent_cancels_running_children(self):
        g = RunGraph()
        parent = g.spawn("t1", RunRole.BUILDER)
        c1 = g.spawn("t1", RunRole.REVIEWER, parent_run_id=parent)
        c2 = g.spawn("t1", RunRole.DEBUGGER, parent_run_id=parent)
        g.update_status(c1, RunStatus.RUNNING)
        g.update_status(c2, RunStatus.RUNNING)
        
        cascaded = g.update_status(parent, RunStatus.KILLED)
        
        assert g.get(c1).status == RunStatus.KILLED
        assert g.get(c2).status == RunStatus.KILLED
        assert c1 in cascaded
        assert c2 in cascaded
    
    def test_killed_parent_cancels_pending_children(self):
        """PENDING children should also be cancelled, not survive."""
        g = RunGraph()
        parent = g.spawn("t1", RunRole.BUILDER)
        child = g.spawn("t1", RunRole.REVIEWER, parent_run_id=parent)
        # Child is PENDING (default)
        
        g.update_status(parent, RunStatus.KILLED)
        
        assert g.get(child).status == RunStatus.KILLED
    
    def test_timed_out_parent_cancels_children(self):
        g = RunGraph()
        parent = g.spawn("t1", RunRole.BUILDER)
        child = g.spawn("t1", RunRole.REVIEWER, parent_run_id=parent)
        
        g.update_status(parent, RunStatus.TIMED_OUT)
        
        assert g.get(child).status == RunStatus.KILLED
    
    def test_detached_children_NOT_cancelled(self):
        """Non-blocking children should NOT be auto-cancelled."""
        g = RunGraph()
        parent = g.spawn("t1", RunRole.BUILDER)
        child = g.spawn("t1", RunRole.RESEARCHER, parent_run_id=parent, blocking=False)
        g.update_status(child, RunStatus.RUNNING)
        
        g.update_status(parent, RunStatus.KILLED)
        
        # Detached child survives
        assert g.get(child).status == RunStatus.RUNNING


# ─────────────────────────────────────────────────────────────────
# 3. Circuit breaker — semantic equivalence
# ─────────────────────────────────────────────────────────────────

class TestSemanticBreaker:
    def test_whitespace_variations_same_signature(self):
        cb = CircuitBreaker()
        s1 = cb.get_error_signature(ValueError("Module foo missing"))
        s2 = cb.get_error_signature(ValueError("Module  foo missing "))
        s3 = cb.get_error_signature(ValueError("module foo missing"))
        assert s1 == s2 == s3
    
    def test_trips_on_semantically_same_errors(self):
        cb = CircuitBreaker(error_threshold=3, window_seconds=60)
        cb.record_error("t1", cb.get_error_signature(ValueError("Module foo missing")))
        cb.record_error("t1", cb.get_error_signature(ValueError("module  foo missing")))
        cb.record_error("t1", cb.get_error_signature(ValueError("Module foo missing.")))
        
        assert cb.should_trip("t1")
    
    def test_approach_normalization_blocks_rewording(self):
        cb = CircuitBreaker(window_seconds=60)
        cb.record_approach("t1", "Edit setup.py", "failed", "")
        
        assert not cb.can_retry("t1", "edit setup.py")
        assert not cb.can_retry("t1", "Edit  setup.py ")
        assert not cb.can_retry("t1", "EDIT SETUP.PY.")


# ─────────────────────────────────────────────────────────────────
# 4. Per-run timeout, not just role default
# ─────────────────────────────────────────────────────────────────

class TestPerRunTimeout:
    def test_per_run_timeout_honored(self):
        graph = RunGraph()
        controller = SpawnController(graph, spawn_fn=lambda c: SpawnResult(run_id="x", success=True))
        
        # Spawn with short timeout
        result = controller.spawn(SpawnConfig(role=RunRole.BUILDER, task_id="t1", timeout_seconds=1))
        run_id = result.run_id
        
        # Manually backdate start so it's already expired
        controller._active_runs[run_id]["start_time"] = time.time() - 5
        
        timed_out = controller.check_timeouts()
        assert run_id in timed_out
    
    def test_spawn_returns_graph_run_id_not_backend_handle(self):
        graph = RunGraph()
        # Backend returns its own different ID
        controller = SpawnController(graph, spawn_fn=lambda c: SpawnResult(run_id="backend-xyz", success=True))
        
        result = controller.spawn(SpawnConfig(role=RunRole.BUILDER, task_id="t1"))
        
        # Returned run_id should be the graph's, not backend's
        assert result.run_id != "backend-xyz"
        assert graph.get(result.run_id) is not None


# ─────────────────────────────────────────────────────────────────
# 5. Persistence/recovery
# ─────────────────────────────────────────────────────────────────

class TestPersistence:
    def test_run_graph_save_load_roundtrip(self, tmp_path):
        g = RunGraph()
        parent = g.spawn("t1", RunRole.BUILDER)
        child = g.spawn("t1", RunRole.REVIEWER, parent_run_id=parent)
        g.update_status(child, RunStatus.RUNNING)
        
        path = str(tmp_path / "graph.json")
        g.save(path)
        
        g2 = RunGraph.load(path)
        assert g2.count() == 2
        assert g2.get(parent) is not None
        assert g2.get(child).status == RunStatus.RUNNING
        assert child in g2.get(parent).blocking_children
    
    def test_circuit_breaker_save_load(self, tmp_path):
        cb = CircuitBreaker(error_threshold=3)
        cb.record_error("t1", "err sig")
        cb.record_approach("t1", "approach a", "fail", "ev")
        
        path = str(tmp_path / "cb.json")
        cb.save(path)
        
        cb2 = CircuitBreaker.load(path)
        assert len(cb2.get_rejections("t1")) == 1
        assert not cb2.can_retry("t1", "approach a")
    
    def test_spawn_controller_rehydrate(self):
        graph = RunGraph()
        controller = SpawnController(graph, spawn_fn=lambda c: SpawnResult(run_id="x", success=True))
        controller.spawn(SpawnConfig(role=RunRole.BUILDER, task_id="t1"))
        
        snapshot = controller.to_dict()
        
        # New controller, rehydrate
        graph2 = RunGraph.from_dict(graph.to_dict())
        controller2 = SpawnController(graph2)
        controller2.rehydrate(snapshot)
        
        assert controller2.get_active_count() == 1


# ─────────────────────────────────────────────────────────────────
# 6. PARTIAL as first-class state
# ─────────────────────────────────────────────────────────────────

class TestPartialFirstClass:
    def test_partial_requires_artifacts(self):
        g = RunGraph()
        run_id = g.spawn("t1", RunRole.BUILDER)
        
        with pytest.raises(ValueError, match="artifact"):
            g.mark_partial(run_id, "tried but incomplete", artifact_refs=[])
    
    def test_partial_with_artifacts_succeeds(self):
        g = RunGraph()
        run_id = g.spawn("t1", RunRole.BUILDER)
        
        g.mark_partial(run_id, "got halfway", artifact_refs=["src/foo.py", "tests/foo_test.py"])
        
        node = g.get(run_id)
        assert node.status == RunStatus.PARTIAL
        assert "src/foo.py" in node.artifact_refs
        assert node.summary == "got halfway"
    
    def test_progress_recording(self):
        g = RunGraph()
        run_id = g.spawn("t1", RunRole.BUILDER)
        
        g.record_progress(run_id, timestamp=1000.0)
        assert g.get(run_id).last_progress_at == 1000.0

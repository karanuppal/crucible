"""Phase 2 tests: Run graph model."""

import pytest

from crucible.runner.run_graph import (
    RunGraph, RunStatus, RunRole,
)


class TestRunGraphSpawn:
    def test_spawn_creates_node(self):
        g = RunGraph()
        run_id = g.spawn("t1", RunRole.BUILDER)
        assert run_id.startswith("run-")
        assert g.count() == 1
    
    def test_spawn_with_parent(self):
        g = RunGraph()
        parent = g.spawn("t1", RunRole.BUILDER)
        child = g.spawn("t1", RunRole.REVIEWER, parent_run_id=parent)
        
        parent_node = g.get(parent)
        assert child in parent_node.blocking_children
    
    def test_non_blocking_child(self):
        g = RunGraph()
        parent = g.spawn("t1", RunRole.BUILDER)
        child = g.spawn("t1", RunRole.RESEARCHER, parent_run_id=parent, blocking=False)
        
        parent_node = g.get(parent)
        assert child in parent_node.detached_children
        assert child not in parent_node.blocking_children


class TestRunGraphStatus:
    def test_update_status(self):
        g = RunGraph()
        run_id = g.spawn("t1", RunRole.BUILDER)
        g.update_status(run_id, RunStatus.RUNNING)
        
        node = g.get(run_id)
        assert node.status == RunStatus.RUNNING
    
    def test_partial_is_terminal(self):
        g = RunGraph()
        run_id = g.spawn("t1", RunRole.BUILDER)
        g.update_status(run_id, RunStatus.PARTIAL)
        
        assert g.is_blocking_child_complete(run_id)


class TestBlockingSemantics:
    def test_blocking_child_incomplete(self):
        g = RunGraph()
        parent = g.spawn("t1", RunRole.BUILDER)
        child = g.spawn("t1", RunRole.REVIEWER, parent_run_id=parent)
        
        # Child not in terminal state
        assert not g.is_blocking_child_complete(parent)
    
    def test_blocking_child_complete(self):
        g = RunGraph()
        parent = g.spawn("t1", RunRole.BUILDER)
        child = g.spawn("t1", RunRole.REVIEWER, parent_run_id=parent)
        
        g.update_status(child, RunStatus.COMPLETE)
        assert g.is_blocking_child_complete(parent)
    
    def test_detached_survives_cancellation(self):
        g = RunGraph()
        parent = g.spawn("t1", RunRole.BUILDER)
        child = g.spawn("t1", RunRole.RESEARCHER, parent_run_id=parent, blocking=False)
        
        # Cancel parent - detached child should remain in its own state
        g.update_status(parent, RunStatus.KILLED)
        
        child_node = g.get(child)
        # Detached child status unchanged
        assert child_node.status == RunStatus.PENDING


class TestActiveRuns:
    def test_get_active_runs(self):
        g = RunGraph()
        r1 = g.spawn("t1", RunRole.BUILDER)
        r2 = g.spawn("t1", RunRole.REVIEWER)
        
        g.update_status(r1, RunStatus.RUNNING)
        g.update_status(r2, RunStatus.COMPLETE)
        
        active = g.get_active_runs()
        assert len(active) == 1
        assert active[0].run_id == r1
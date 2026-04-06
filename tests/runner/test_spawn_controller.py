"""Phase 2 tests: Spawn controller."""

import pytest
import time

from agentic_harness.runner.spawn_controller import (
    SpawnController, SpawnConfig, SpawnResult, ROLE_TEMPLATES,
)
from agentic_harness.runner.run_graph import RunGraph, RunRole, RunStatus


class TestRoleTemplates:
    def test_all_roles_have_templates(self):
        for role in RunRole:
            assert role in ROLE_TEMPLATES
            t = ROLE_TEMPLATES[role]
            assert "timeout_seconds" in t
            assert "retry_budget" in t
    
    def test_builder_timeout(self):
        assert ROLE_TEMPLATES[RunRole.BUILDER]["timeout_seconds"] == 600


class TestSpawnController:
    def test_spawn_applies_role_defaults(self):
        graph = RunGraph()
        controller = SpawnController(graph)
        
        def mock_spawn(cfg: SpawnConfig) -> SpawnResult:
            return SpawnResult(run_id=cfg.task_id + "-mock", success=True)
        
        controller._spawn_fn = mock_spawn
        
        result = controller.spawn(SpawnConfig(role=RunRole.BUILDER, task_id="t1"))
        
        assert result.success
        # The graph has the run under the ID from spawn(), mock just returns a result
        assert controller.get_active_count() == 1
    
    def test_spawn_tracks_active(self):
        graph = RunGraph()
        controller = SpawnController(graph)
        
        def mock_spawn(cfg: SpawnConfig) -> SpawnResult:
            return SpawnResult(run_id="test-123", success=True)
        
        controller._spawn_fn = mock_spawn
        
        controller.spawn(SpawnConfig(role=RunRole.BUILDER, task_id="t1"))
        
        assert controller.get_active_count() == 1
    
    def test_check_timeouts(self):
        graph = RunGraph()
        controller = SpawnController(graph)
        
        # Manually add a running job
        run_id = graph.spawn("t1", RunRole.BUILDER)
        graph.update_status(run_id, RunStatus.RUNNING)
        controller._active_runs[run_id] = time.time() - 1000  # Started long ago
        
        timed_out = controller.check_timeouts()
        
        assert run_id in timed_out
        assert graph.get(run_id).status == RunStatus.TIMED_OUT
    
    def test_complete_run(self):
        graph = RunGraph()
        controller = SpawnController(graph)
        
        def mock_spawn(cfg: SpawnConfig) -> SpawnResult:
            return SpawnResult(run_id=cfg.task_id + "-mock", success=True)
        
        controller._spawn_fn = mock_spawn
        
        result = controller.spawn(SpawnConfig(role=RunRole.BUILDER, task_id="t1"))
        
        # Get the actual run_id from the graph (not the mock result)
        runs = graph.get_all_runs()
        actual_run_id = runs[0].run_id
        
        controller.complete_run(actual_run_id, RunStatus.COMPLETE)
        
        assert controller.get_active_count() == 0
        assert graph.get(actual_run_id).status == RunStatus.COMPLETE
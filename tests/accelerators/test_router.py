"""Phase 6 tests: router with fallback semantics."""

import pytest
import time

from crucible.accelerators.capabilities import (
    BackendCapabilities, BackendCapabilityMatrix, Capability,
)
from crucible.accelerators.adapters import (
    InMemoryAdapter, AdapterRunSpec, AdapterStatus,
)
from crucible.accelerators.router import (
    Router, FailoverEvent, BackendUnavailableError,
)


def _setup(backends_config):
    """Helper: build matrix + adapters from a list of (id, caps, outcome)."""
    matrix = BackendCapabilityMatrix()
    adapters = {}
    for bid, caps_set, outcome in backends_config:
        caps = BackendCapabilities(backend_id=bid, supports=caps_set)
        matrix.register(caps)
        adapters[bid] = InMemoryAdapter(
            bid, caps,
            simulated_runtime_s=0.001,
            simulated_outcome=outcome,
        )
    return matrix, adapters


class TestSelection:
    def test_preferred_backend_used(self):
        matrix, adapters = _setup([
            ("b1", {Capability.FILE_WRITE}, AdapterStatus.COMPLETE),
            ("b2", {Capability.FILE_WRITE}, AdapterStatus.COMPLETE),
        ])
        router = Router(matrix, adapters, preferred_order=["b2", "b1"])
        
        spec = AdapterRunSpec(spec_id="s1", prompt="x", cwd="/tmp")
        selected = router.select_backend(spec)
        assert selected == "b2"
    
    def test_required_capabilities_filter(self):
        matrix, adapters = _setup([
            ("b1", {Capability.FILE_WRITE}, AdapterStatus.COMPLETE),
            ("b2", {Capability.FILE_WRITE, Capability.NETWORK}, AdapterStatus.COMPLETE),
        ])
        router = Router(matrix, adapters, preferred_order=["b1", "b2"])
        
        spec = AdapterRunSpec(
            spec_id="s1", prompt="x", cwd="/tmp",
            required_capabilities={Capability.NETWORK},
        )
        selected = router.select_backend(spec)
        assert selected == "b2"  # b1 doesn't have NETWORK
    
    def test_no_capable_backend_raises(self):
        matrix, adapters = _setup([
            ("b1", {Capability.FILE_WRITE}, AdapterStatus.COMPLETE),
        ])
        router = Router(matrix, adapters)
        
        spec = AdapterRunSpec(
            spec_id="s1", prompt="x", cwd="/tmp",
            required_capabilities={Capability.NETWORK},
        )
        with pytest.raises(BackendUnavailableError):
            router.select_backend(spec)


class TestFallback:
    def test_failover_to_next_backend(self):
        matrix, adapters = _setup([
            ("b1", {Capability.FILE_WRITE}, AdapterStatus.FAILED),
            ("b2", {Capability.FILE_WRITE}, AdapterStatus.COMPLETE),
        ])
        router = Router(matrix, adapters, preferred_order=["b1", "b2"])
        
        spec = AdapterRunSpec(spec_id="s1", prompt="x", cwd="/tmp", timeout_seconds=1)
        result = router.execute_with_fallback(spec)
        
        assert result.status == AdapterStatus.COMPLETE
        # Failover event recorded
        events = router.get_failover_events()
        assert len(events) >= 1
        assert any(e.from_backend == "b1" and e.to_backend == "b2" for e in events)
    
    def test_no_duplicate_attempts_on_same_backend(self):
        matrix, adapters = _setup([
            ("b1", {Capability.FILE_WRITE}, AdapterStatus.FAILED),
            ("b2", {Capability.FILE_WRITE}, AdapterStatus.FAILED),
        ])
        router = Router(matrix, adapters, preferred_order=["b1", "b2"])
        
        spec = AdapterRunSpec(spec_id="s1", prompt="x", cwd="/tmp", timeout_seconds=1)
        router.execute_with_fallback(spec, max_attempts=5)
        
        # Each backend attempted at most once
        attempted = router._attempted
        b1_attempts = sum(1 for (sid, bid) in attempted if sid == "s1" and bid == "b1")
        b2_attempts = sum(1 for (sid, bid) in attempted if sid == "s1" and bid == "b2")
        assert b1_attempts == 1
        assert b2_attempts == 1


class TestPersistence:
    def test_failover_state_persists(self, tmp_path):
        matrix, adapters = _setup([
            ("b1", {Capability.FILE_WRITE}, AdapterStatus.FAILED),
            ("b2", {Capability.FILE_WRITE}, AdapterStatus.COMPLETE),
        ])
        state_path = str(tmp_path / "router.json")
        
        r1 = Router(matrix, adapters, preferred_order=["b1", "b2"], state_path=state_path)
        spec = AdapterRunSpec(spec_id="s1", prompt="x", cwd="/tmp", timeout_seconds=1)
        r1.execute_with_fallback(spec)
        
        # Reload
        r2 = Router(matrix, adapters, preferred_order=["b1", "b2"], state_path=state_path)
        events = r2.get_failover_events()
        assert len(events) >= 1
    
    def test_no_silent_artifact_loss(self):
        """When a backend produces partial artifacts then fails, those artifacts
        are recorded in the failover event."""
        # b1 produces artifacts but with FAILED status
        matrix = BackendCapabilityMatrix()
        b1_caps = BackendCapabilities(
            backend_id="b1",
            supports={Capability.FILE_WRITE, Capability.ARTIFACT_PRODUCTION},
        )
        b2_caps = BackendCapabilities(
            backend_id="b2",
            supports={Capability.FILE_WRITE, Capability.ARTIFACT_PRODUCTION},
        )
        matrix.register(b1_caps)
        matrix.register(b2_caps)
        
        adapters = {
            "b1": InMemoryAdapter("b1", b1_caps, simulated_runtime_s=0.001,
                                   simulated_outcome=AdapterStatus.PARTIAL,
                                   produces_artifacts=True),
            "b2": InMemoryAdapter("b2", b2_caps, simulated_runtime_s=0.001,
                                   simulated_outcome=AdapterStatus.COMPLETE,
                                   produces_artifacts=True),
        }
        router = Router(matrix, adapters, preferred_order=["b1", "b2"])
        
        spec = AdapterRunSpec(spec_id="s1", prompt="x", cwd="/tmp", timeout_seconds=1)
        result = router.execute_with_fallback(spec)
        
        # Artifacts from b1 attempt are preserved in failover events
        events = router.get_failover_events()
        b1_events = [e for e in events if e.from_backend == "b1"]
        assert len(b1_events) > 0
        assert any(e.artifacts_preserved for e in b1_events)

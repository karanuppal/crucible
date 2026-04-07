"""Phase 6 tests: backend adapters and semantic parity."""

import pytest

from crucible.accelerators.capabilities import (
    BackendCapabilities, Capability,
)
from crucible.accelerators.adapters import (
    InMemoryAdapter, AdapterRunSpec, AdapterStatus,
)


def _caps(bid="b1"):
    return BackendCapabilities(
        backend_id=bid,
        supports={Capability.FILE_WRITE, Capability.SHELL_EXEC, Capability.ARTIFACT_PRODUCTION},
    )


class TestSpawnPollCollect:
    def test_lifecycle(self):
        adapter = InMemoryAdapter("b1", _caps("b1"), simulated_runtime_s=0.001)
        spec = AdapterRunSpec(spec_id="s1", prompt="x", cwd="/tmp")
        
        handle = adapter.spawn(spec)
        assert handle.backend_id == "b1"
        
        # Wait for completion
        import time
        time.sleep(0.05)
        
        result = adapter.collect(handle)
        assert result.status == AdapterStatus.COMPLETE
        assert len(result.artifact_paths) > 0
    
    def test_kill_terminates_run(self):
        adapter = InMemoryAdapter("b1", _caps("b1"), simulated_runtime_s=10)
        spec = AdapterRunSpec(spec_id="s1", prompt="x", cwd="/tmp")
        handle = adapter.spawn(spec)
        
        adapter.kill(handle)
        result = adapter.collect(handle)
        assert result.status == AdapterStatus.KILLED


class TestRequiredCapabilities:
    def test_missing_capability_rejected(self):
        adapter = InMemoryAdapter("b1", _caps("b1"))
        spec = AdapterRunSpec(
            spec_id="s1", prompt="x", cwd="/tmp",
            required_capabilities={Capability.NETWORK},
        )
        with pytest.raises(ValueError, match="not support"):
            adapter.spawn(spec)


class TestSemanticParity:
    def test_two_backends_same_lifecycle(self):
        a1 = InMemoryAdapter("b1", _caps("b1"), simulated_runtime_s=0.001)
        a2 = InMemoryAdapter("b2", _caps("b2"), simulated_runtime_s=0.001)
        
        spec = AdapterRunSpec(spec_id="s1", prompt="x", cwd="/tmp")
        
        h1 = a1.spawn(spec)
        h2 = a2.spawn(spec)
        
        import time
        time.sleep(0.05)
        
        r1 = a1.collect(h1)
        r2 = a2.collect(h2)
        
        # Same terminal status across backends
        assert r1.status == r2.status
        # Both produce artifacts
        assert len(r1.artifact_paths) == len(r2.artifact_paths)
    
    def test_failure_status_consistent(self):
        a = InMemoryAdapter(
            "b1", _caps("b1"),
            simulated_runtime_s=0.001,
            simulated_outcome=AdapterStatus.FAILED,
            produces_artifacts=False,
        )
        spec = AdapterRunSpec(spec_id="s1", prompt="x", cwd="/tmp")
        handle = a.spawn(spec)
        
        import time
        time.sleep(0.05)
        
        result = a.collect(handle)
        assert result.status == AdapterStatus.FAILED
        assert result.artifact_paths == []

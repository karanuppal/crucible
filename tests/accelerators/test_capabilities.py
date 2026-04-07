"""Phase 6 tests: backend capability matrix."""

import pytest

from crucible.accelerators.capabilities import (
    BackendCapabilities, BackendCapabilityMatrix, Capability,
    CapabilityMismatchError,
)


def _basic(bid="b1", caps=None):
    return BackendCapabilities(
        backend_id=bid,
        supports=set(caps or [Capability.FILE_WRITE, Capability.SHELL_EXEC]),
    )


class TestRegistry:
    def test_register_and_get(self):
        m = BackendCapabilityMatrix()
        m.register(_basic("b1"))
        assert m.get("b1") is not None
    
    def test_find_capable(self):
        m = BackendCapabilityMatrix()
        m.register(_basic("b1", [Capability.FILE_WRITE]))
        m.register(_basic("b2", [Capability.FILE_WRITE, Capability.NETWORK]))
        
        results = m.find_capable({Capability.NETWORK})
        assert len(results) == 1
        assert results[0].backend_id == "b2"
    
    def test_find_capable_empty(self):
        m = BackendCapabilityMatrix()
        m.register(_basic("b1", [Capability.FILE_WRITE]))
        results = m.find_capable({Capability.NETWORK})
        assert results == []


class TestObservedBehavior:
    def test_undeclared_capability_rejected(self):
        m = BackendCapabilityMatrix()
        m.register(_basic("b1", [Capability.FILE_WRITE]))
        
        with pytest.raises(CapabilityMismatchError, match="undeclared"):
            m.verify_observed_behavior("b1", {Capability.NETWORK})
    
    def test_declared_capability_accepted(self):
        m = BackendCapabilityMatrix()
        m.register(_basic("b1", [Capability.FILE_WRITE, Capability.NETWORK]))
        # Should not raise
        m.verify_observed_behavior("b1", {Capability.FILE_WRITE})
    
    def test_unknown_backend_rejected(self):
        m = BackendCapabilityMatrix()
        with pytest.raises(CapabilityMismatchError, match="Unknown"):
            m.verify_observed_behavior("nonexistent", set())


class TestPersistence:
    def test_save_load(self, tmp_path):
        m1 = BackendCapabilityMatrix()
        m1.register(_basic("b1", [Capability.FILE_WRITE, Capability.SHELL_EXEC]))
        m1.register(_basic("b2", [Capability.NETWORK]))
        
        path = str(tmp_path / "matrix.json")
        m1.save(path)
        
        m2 = BackendCapabilityMatrix.load(path)
        assert m2.get("b1") is not None
        assert Capability.FILE_WRITE in m2.get("b1").supports
        assert m2.get("b2").supports == {Capability.NETWORK}

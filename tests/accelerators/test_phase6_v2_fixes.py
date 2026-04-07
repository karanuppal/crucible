"""Phase 6 v2 adversarial fixes."""

import os
import json
import pytest

from crucible.accelerators.capabilities import (
    BackendCapabilities, BackendCapabilityMatrix, Capability,
    CapabilityMismatchError,
)
from crucible.accelerators.adapters import (
    InMemoryAdapter, AdapterRunSpec, AdapterStatus,
)
from crucible.accelerators.router import Router


# ─────────────────────────────────────────────────────────────────
# Fix 1: capability over-claim detection
# ─────────────────────────────────────────────────────────────────

class TestOverclaim:
    def test_overclaim_rejected(self):
        m = BackendCapabilityMatrix()
        m.register(BackendCapabilities(
            backend_id="b1",
            supports={Capability.FILE_WRITE, Capability.NETWORK},
        ))
        # Required: NETWORK. Observed: only FILE_WRITE → backend over-claimed
        with pytest.raises(CapabilityMismatchError, match="declared but did not deliver"):
            m.verify_observed_behavior(
                "b1",
                observed_capabilities={Capability.FILE_WRITE},
                required_capabilities={Capability.NETWORK},
            )
    
    def test_no_overclaim_when_delivered(self):
        m = BackendCapabilityMatrix()
        m.register(BackendCapabilities(
            backend_id="b1",
            supports={Capability.FILE_WRITE, Capability.NETWORK},
        ))
        # All required delivered — no error
        m.verify_observed_behavior(
            "b1",
            observed_capabilities={Capability.FILE_WRITE, Capability.NETWORK},
            required_capabilities={Capability.NETWORK},
        )


# ─────────────────────────────────────────────────────────────────
# Fix 2: Router state persisted on every mutation
# ─────────────────────────────────────────────────────────────────

class TestRouterDurability:
    def test_failover_state_persisted_immediately(self, tmp_path):
        matrix = BackendCapabilityMatrix()
        b1_caps = BackendCapabilities(backend_id="b1", supports={Capability.FILE_WRITE})
        b2_caps = BackendCapabilities(backend_id="b2", supports={Capability.FILE_WRITE})
        matrix.register(b1_caps)
        matrix.register(b2_caps)
        
        adapters = {
            "b1": InMemoryAdapter("b1", b1_caps, simulated_runtime_s=0.001,
                                   simulated_outcome=AdapterStatus.FAILED),
            "b2": InMemoryAdapter("b2", b2_caps, simulated_runtime_s=0.001,
                                   simulated_outcome=AdapterStatus.COMPLETE),
        }
        
        state_path = str(tmp_path / "router.json")
        router = Router(matrix, adapters, preferred_order=["b1", "b2"], state_path=state_path)
        
        spec = AdapterRunSpec(spec_id="s1", prompt="x", cwd="/tmp", timeout_seconds=1)
        router.execute_with_fallback(spec)
        
        # File must exist with failover events
        assert os.path.isfile(state_path)
        with open(state_path) as f:
            data = json.load(f)
        assert len(data["failovers"]) >= 1
    
    def test_attempted_set_persisted(self, tmp_path):
        matrix = BackendCapabilityMatrix()
        caps = BackendCapabilities(backend_id="b1", supports={Capability.FILE_WRITE})
        matrix.register(caps)
        
        adapters = {
            "b1": InMemoryAdapter("b1", caps, simulated_runtime_s=0.001,
                                   simulated_outcome=AdapterStatus.FAILED),
        }
        
        state_path = str(tmp_path / "router.json")
        r1 = Router(matrix, adapters, state_path=state_path)
        spec = AdapterRunSpec(spec_id="s1", prompt="x", cwd="/tmp", timeout_seconds=1)
        r1.execute_with_fallback(spec)
        
        # Reload
        r2 = Router(matrix, adapters, state_path=state_path)
        # Same backend should not be retried (already attempted)
        assert ("s1", "b1") in r2._attempted

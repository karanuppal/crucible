"""Phase 6: Backend capability declarations and matrix.

Each backend declares what it can and cannot do. The router uses this
matrix to pick a backend for a given RunSpec, with fallback semantics.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class Capability(str, Enum):
    """Capabilities a backend may support."""
    FILE_WRITE = "file_write"
    SHELL_EXEC = "shell_exec"
    NETWORK = "network"
    LONG_RUNNING = "long_running"  # >5 min runs
    STREAMING_PROGRESS = "streaming_progress"
    INTERRUPTIBLE = "interruptible"  # can be killed mid-run
    ARTIFACT_PRODUCTION = "artifact_production"
    SUB_AGENT_SPAWN = "sub_agent_spawn"


@dataclass
class BackendCapabilities:
    """Declared capabilities for a backend."""
    backend_id: str
    supports: set[Capability] = field(default_factory=set)
    max_concurrent_runs: int = 1
    declared_models: list[str] = field(default_factory=list)
    
    def can(self, capability: Capability) -> bool:
        return capability in self.supports
    
    def supports_all(self, required: set[Capability]) -> bool:
        return required.issubset(self.supports)


class CapabilityMismatchError(Exception):
    """Raised when a backend's observed behavior contradicts its declarations."""
    pass


class BackendCapabilityMatrix:
    """Registry of all known backends and their declared capabilities.
    
    The matrix is the single source of truth for routing decisions.
    """
    
    def __init__(self) -> None:
        self._backends: dict[str, BackendCapabilities] = {}
    
    def register(self, caps: BackendCapabilities) -> None:
        self._backends[caps.backend_id] = caps
    
    def get(self, backend_id: str) -> BackendCapabilities | None:
        return self._backends.get(backend_id)
    
    def find_capable(self, required: set[Capability]) -> list[BackendCapabilities]:
        """Return all backends that support all required capabilities."""
        return [b for b in self._backends.values() if b.supports_all(required)]
    
    def list_all(self) -> list[BackendCapabilities]:
        return list(self._backends.values())
    
    def verify_observed_behavior(
        self,
        backend_id: str,
        observed_capabilities: set[Capability],
        *,
        required_capabilities: set[Capability] | None = None,
    ) -> None:
        """Raise CapabilityMismatchError if observed behavior contradicts declarations.
        
        Two-way check:
        - Backend cannot demonstrate UNDECLARED capabilities (security)
        - Backend cannot CLAIM a required capability it didn't demonstrate (overclaim)
        
        If required_capabilities is provided, every required capability must be
        in observed_capabilities, otherwise the backend over-claimed.
        """
        caps = self._backends.get(backend_id)
        if caps is None:
            raise CapabilityMismatchError(f"Unknown backend: {backend_id}")
        
        # Undeclared (under-claim attack)
        undeclared = observed_capabilities - caps.supports
        if undeclared:
            raise CapabilityMismatchError(
                f"Backend {backend_id} demonstrated undeclared capabilities: {sorted(undeclared)}"
            )
        
        # Over-claim: required capabilities must actually have been delivered
        if required_capabilities is not None:
            promised_but_missing = (caps.supports & required_capabilities) - observed_capabilities
            if promised_but_missing:
                raise CapabilityMismatchError(
                    f"Backend {backend_id} declared but did not deliver: {sorted(promised_but_missing)}"
                )
    
    def to_dict(self) -> dict[str, Any]:
        return {
            "backends": {
                bid: {
                    "backend_id": b.backend_id,
                    "supports": sorted(c.value for c in b.supports),
                    "max_concurrent_runs": b.max_concurrent_runs,
                    "declared_models": list(b.declared_models),
                }
                for bid, b in self._backends.items()
            }
        }
    
    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "BackendCapabilityMatrix":
        m = cls()
        for bid, b_data in data.get("backends", {}).items():
            m.register(BackendCapabilities(
                backend_id=b_data["backend_id"],
                supports={Capability(c) for c in b_data.get("supports", [])},
                max_concurrent_runs=b_data.get("max_concurrent_runs", 1),
                declared_models=list(b_data.get("declared_models", [])),
            ))
        return m
    
    def save(self, path: str) -> None:
        import json
        import os
        tmp = path + ".tmp"
        with open(tmp, "w") as f:
            json.dump(self.to_dict(), f, indent=2)
        os.replace(tmp, path)
    
    @classmethod
    def load(cls, path: str) -> "BackendCapabilityMatrix":
        import json
        with open(path) as f:
            return cls.from_dict(json.load(f))

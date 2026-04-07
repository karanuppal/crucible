"""Phase 6: Backend adapters with semantic parity.

Each adapter normalizes a backend's lifecycle to the same shape:
- spawn → returns AdapterRunHandle
- poll → AdapterRunStatus
- collect → AdapterRunResult (artifacts + summary)
- kill → idempotent termination

All adapters guarantee:
- Same set of terminal statuses (RUNNING, COMPLETE, FAILED, KILLED, TIMED_OUT, PARTIAL)
- Artifact references included on terminal
- No silent state divergence
"""

from __future__ import annotations

import time
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from agentic_harness.accelerators.capabilities import Capability, BackendCapabilities


class AdapterStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETE = "complete"
    FAILED = "failed"
    KILLED = "killed"
    TIMED_OUT = "timed_out"
    PARTIAL = "partial"


@dataclass
class AdapterRunSpec:
    """A normalized run specification across all backends."""
    spec_id: str
    prompt: str
    cwd: str
    timeout_seconds: int = 300
    required_capabilities: set[Capability] = field(default_factory=set)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class AdapterRunHandle:
    """Opaque handle for a spawned run."""
    handle_id: str
    backend_id: str
    spawned_at: float
    spec_id: str


@dataclass
class AdapterRunResult:
    """Terminal result from a run."""
    handle_id: str
    status: AdapterStatus
    artifact_paths: list[str] = field(default_factory=list)
    summary: str = ""
    error: str = ""
    started_at: float = 0.0
    finished_at: float = 0.0


class BackendAdapter(ABC):
    """Abstract backend adapter with semantic parity contract."""
    
    @abstractmethod
    def backend_id(self) -> str:
        ...
    
    @abstractmethod
    def declared_capabilities(self) -> BackendCapabilities:
        ...
    
    @abstractmethod
    def spawn(self, spec: AdapterRunSpec) -> AdapterRunHandle:
        ...
    
    @abstractmethod
    def poll(self, handle: AdapterRunHandle) -> AdapterStatus:
        ...
    
    @abstractmethod
    def collect(self, handle: AdapterRunHandle) -> AdapterRunResult:
        ...
    
    @abstractmethod
    def kill(self, handle: AdapterRunHandle) -> None:
        ...


# ─────────────────────────────────────────────────────────────────
# Reference adapter implementations (in-process for testing)
# ─────────────────────────────────────────────────────────────────

class InMemoryAdapter(BackendAdapter):
    """Reference adapter for testing semantic parity.
    
    Simulates a backend with controllable behavior.
    """
    
    def __init__(
        self,
        backend_id: str,
        capabilities: BackendCapabilities,
        *,
        simulated_runtime_s: float = 0.01,
        simulated_outcome: AdapterStatus = AdapterStatus.COMPLETE,
        produces_artifacts: bool = True,
    ) -> None:
        self._backend_id = backend_id
        self._caps = capabilities
        self._runtime = simulated_runtime_s
        self._outcome = simulated_outcome
        self._produces_artifacts = produces_artifacts
        self._runs: dict[str, dict[str, Any]] = {}
    
    def backend_id(self) -> str:
        return self._backend_id
    
    def declared_capabilities(self) -> BackendCapabilities:
        return self._caps
    
    def spawn(self, spec: AdapterRunSpec) -> AdapterRunHandle:
        # Verify required capabilities
        if not self._caps.supports_all(spec.required_capabilities):
            raise ValueError(
                f"Backend {self._backend_id} does not support required capabilities: "
                f"{spec.required_capabilities - self._caps.supports}"
            )
        
        handle_id = f"{self._backend_id}-{uuid.uuid4().hex[:8]}"
        now = time.time()
        self._runs[handle_id] = {
            "spec": spec,
            "status": AdapterStatus.RUNNING,
            "started_at": now,
            "finishes_at": now + self._runtime,
            "killed": False,
        }
        return AdapterRunHandle(
            handle_id=handle_id,
            backend_id=self._backend_id,
            spawned_at=now,
            spec_id=spec.spec_id,
        )
    
    def poll(self, handle: AdapterRunHandle) -> AdapterStatus:
        run = self._runs.get(handle.handle_id)
        if not run:
            return AdapterStatus.FAILED
        if run["killed"]:
            return AdapterStatus.KILLED
        if time.time() >= run["finishes_at"]:
            return self._outcome
        return AdapterStatus.RUNNING
    
    def collect(self, handle: AdapterRunHandle) -> AdapterRunResult:
        run = self._runs.get(handle.handle_id)
        if not run:
            return AdapterRunResult(
                handle_id=handle.handle_id,
                status=AdapterStatus.FAILED,
                error="Unknown handle",
            )
        
        status = self.poll(handle)
        artifacts = []
        if self._produces_artifacts and status in {AdapterStatus.COMPLETE, AdapterStatus.PARTIAL}:
            artifacts = [f"/tmp/{handle.handle_id}/output.txt"]
        
        return AdapterRunResult(
            handle_id=handle.handle_id,
            status=status,
            artifact_paths=artifacts,
            summary=f"Run via {self._backend_id}",
            started_at=run["started_at"],
            finished_at=time.time(),
        )
    
    def kill(self, handle: AdapterRunHandle) -> None:
        run = self._runs.get(handle.handle_id)
        if run:
            run["killed"] = True
            run["status"] = AdapterStatus.KILLED

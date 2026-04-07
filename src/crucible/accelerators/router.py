"""Phase 6: Backend routing with fallback semantics.

The router picks a backend for a RunSpec based on:
- Required capabilities
- Preferred backend ordering
- Availability/health

Fallback rules (hard guarantees):
- Never lose artifacts on failover
- Never duplicate work silently
- Failover decisions are auditable (logged)
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from typing import Any

from crucible.accelerators.capabilities import (
    BackendCapabilityMatrix, Capability,
)
from crucible.accelerators.adapters import (
    BackendAdapter, AdapterRunSpec, AdapterRunHandle, AdapterRunResult, AdapterStatus,
)


@dataclass
class FailoverEvent:
    """Audit record of a failover."""
    spec_id: str
    from_backend: str
    to_backend: str
    reason: str
    timestamp: float = field(default_factory=time.time)
    artifacts_preserved: list[str] = field(default_factory=list)


class BackendUnavailableError(Exception):
    pass


class Router:
    """Routes RunSpecs to backends with fallback support.
    
    Hard rules:
    - If a run has produced artifacts before failure, those artifacts are
      preserved in the failover event audit record
    - The same spec_id is never executed twice on the same backend
    - Failover history is durable
    """
    
    def __init__(
        self,
        matrix: BackendCapabilityMatrix,
        adapters: dict[str, BackendAdapter],
        *,
        preferred_order: list[str] | None = None,
        state_path: str | None = None,
    ) -> None:
        self._matrix = matrix
        self._adapters = adapters
        self._preferred = list(preferred_order or [])
        self._state_path = state_path
        self._failovers: list[FailoverEvent] = []
        # Track which (spec_id, backend_id) pairs have been attempted
        self._attempted: set[tuple[str, str]] = set()
        
        if state_path and os.path.exists(state_path):
            self._load()
    
    def select_backend(self, spec: AdapterRunSpec) -> str:
        """Select the best backend for a spec.
        
        Priority:
        1. Preferred backends (in order) that meet requirements
        2. Any other capable backend
        """
        capable = self._matrix.find_capable(spec.required_capabilities)
        capable_ids = {b.backend_id for b in capable}
        
        # Try preferred order first
        for pid in self._preferred:
            if pid in capable_ids and pid in self._adapters:
                if (spec.spec_id, pid) not in self._attempted:
                    return pid
        
        # Try any other capable backend
        for cap in capable:
            bid = cap.backend_id
            if bid in self._adapters and (spec.spec_id, bid) not in self._attempted:
                return bid
        
        raise BackendUnavailableError(
            f"No capable backend available for spec {spec.spec_id} "
            f"(required: {spec.required_capabilities})"
        )
    
    def execute_with_fallback(
        self,
        spec: AdapterRunSpec,
        max_attempts: int = 3,
    ) -> AdapterRunResult:
        """Execute a spec with automatic fallback on failure.
        
        Preserves artifacts from failed attempts in failover audit records.
        """
        last_result: AdapterRunResult | None = None
        last_backend: str | None = None
        
        for attempt in range(max_attempts):
            try:
                backend_id = self.select_backend(spec)
            except BackendUnavailableError:
                if last_result:
                    return last_result
                raise
            
            # Link previous failover event to this new backend
            if self._failovers and not self._failovers[-1].to_backend:
                self._failovers[-1].to_backend = backend_id
            
            self._attempted.add((spec.spec_id, backend_id))
            self._save()  # persist before any work
            adapter = self._adapters[backend_id]
            
            try:
                handle = adapter.spawn(spec)
            except Exception as e:
                # Spawn failure — record failover and try next
                self._failovers.append(FailoverEvent(
                    spec_id=spec.spec_id,
                    from_backend=last_backend or "",
                    to_backend=backend_id,
                    reason=f"spawn failed: {e}",
                ))
                self._save()
                last_backend = backend_id
                continue
            
            # Wait for completion (with timeout)
            deadline = time.time() + spec.timeout_seconds
            while time.time() < deadline:
                status = adapter.poll(handle)
                if status not in {AdapterStatus.RUNNING, AdapterStatus.PENDING}:
                    break
                time.sleep(0.01)
            
            result = adapter.collect(handle)
            
            if result.status == AdapterStatus.COMPLETE:
                self._save()
                return result
            
            # Non-complete result — record a failover event preserving artifacts
            self._failovers.append(FailoverEvent(
                spec_id=spec.spec_id,
                from_backend=backend_id,
                to_backend="",  # filled in on next iteration
                reason=f"run status: {result.status.value}",
                artifacts_preserved=list(result.artifact_paths),
            ))
            self._save()  # persist failover immediately
            
            last_result = result
            last_backend = backend_id
        
        # All attempts exhausted — return last result with artifacts preserved
        self._save()
        return last_result or AdapterRunResult(
            handle_id="",
            status=AdapterStatus.FAILED,
            error="No attempts succeeded",
        )
    
    def get_failover_events(self) -> list[FailoverEvent]:
        return list(self._failovers)
    
    def _save(self) -> None:
        if not self._state_path:
            return
        data = {
            "failovers": [
                {
                    "spec_id": f.spec_id,
                    "from_backend": f.from_backend,
                    "to_backend": f.to_backend,
                    "reason": f.reason,
                    "timestamp": f.timestamp,
                    "artifacts_preserved": list(f.artifacts_preserved),
                }
                for f in self._failovers
            ],
            "attempted": [list(t) for t in self._attempted],
        }
        tmp = self._state_path + ".tmp"
        with open(tmp, "w") as f:
            json.dump(data, f, indent=2)
        os.replace(tmp, self._state_path)
    
    def _load(self) -> None:
        with open(self._state_path) as f:
            data = json.load(f)
        for f_data in data.get("failovers", []):
            self._failovers.append(FailoverEvent(
                spec_id=f_data["spec_id"],
                from_backend=f_data["from_backend"],
                to_backend=f_data["to_backend"],
                reason=f_data["reason"],
                timestamp=f_data["timestamp"],
                artifacts_preserved=list(f_data.get("artifacts_preserved", [])),
            ))
        self._attempted = {tuple(t) for t in data.get("attempted", [])}

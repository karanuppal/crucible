"""Phase 2: Circuit breaker and rejection ledger.

From spec (§9.6, §13):
- Trip on repeated same-error signature
- Track attempted approaches, failure reasons, evidence
- Prevent re-attempting known-bad approaches without new evidence
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any


@dataclass
class RejectionEntry:
    """A single rejected attempt."""
    task_id: str
    attempt: int
    approach: str
    failure_reason: str
    evidence: str
    timestamp: float = field(default_factory=time.time)


class CircuitBreaker:
    """Detects loops and prevents repeated failed approaches.
    
    Trip conditions:
    - repeated same-error signature beyond threshold
    - repeated no-progress iterations beyond threshold
    
    Recovery: must change approach before retry
    """
    
    def __init__(
        self,
        *,
        error_threshold: int = 3,
        no_progress_threshold: int = 3,
        window_seconds: float = 300.0,
    ) -> None:
        self._error_threshold = error_threshold
        self._no_progress_threshold = no_progress_threshold
        self._window_seconds = window_seconds
        self._recent_errors: list[tuple[str, float, str]] = []  # (task_id, timestamp, error_signature)
        self._no_progress_count: dict[str, int] = {}
        self._rejection_ledger: list[RejectionEntry] = []
    
    def record_error(self, task_id: str, error_signature: str) -> None:
        """Record a failure for a task."""
        now = time.time()
        # Add to recent errors
        self._recent_errors.append((task_id, now, error_signature))
        # Prune old entries
        self._recent_errors = [
            (tid, ts, sig) for tid, ts, sig in self._recent_errors
            if now - ts < self._window_seconds
        ]
    
    def should_trip(self, task_id: str) -> bool:
        """Check if circuit should trip for this task."""
        now = time.time()
        # Count recent errors for this task
        task_errors = [
            sig for tid, ts, sig in self._recent_errors
            if tid == task_id and now - ts < self._window_seconds
        ]
        
        # Check for repeated same-error signature
        if len(task_errors) >= self._error_threshold:
            # All errors same signature?
            if len(set(task_errors)) == 1:
                return True
        
        # Check no-progress count
        if self._no_progress_count.get(task_id, 0) >= self._no_progress_threshold:
            return True
        
        return False
    
    def record_no_progress(self, task_id: str) -> None:
        """Record a no-progress iteration."""
        self._no_progress_count[task_id] = self._no_progress_count.get(task_id, 0) + 1
    
    def record_approach(
        self,
        task_id: str,
        approach: str,
        failure_reason: str,
        evidence: str = "",
    ) -> None:
        """Record a rejected approach for audit trail."""
        attempt = len([r for r in self._rejection_ledger if r.task_id == task_id]) + 1
        entry = RejectionEntry(
            task_id=task_id,
            attempt=attempt,
            approach=approach,
            failure_reason=failure_reason,
            evidence=evidence,
        )
        self._rejection_ledger.append(entry)
    
    def get_rejections(self, task_id: str) -> list[RejectionEntry]:
        return [r for r in self._rejection_ledger if r.task_id == task_id]
    
    def can_retry(self, task_id: str, new_approach: str) -> bool:
        """Check if a new approach is allowed.
        
        A new approach is allowed if:
        - It hasn't been tried before
        - Or significant time has passed
        """
        recent = self.get_rejections(task_id)
        if not recent:
            return True
        
        # Check if this exact approach was tried
        tried = {r.approach for r in recent}
        if new_approach in tried:
            # Check if it's been long enough (reset after window)
            last_attempt = max(r.timestamp for r in recent)
            if time.time() - last_attempt < self._window_seconds:
                return False
        
        return True
    
    def reset(self, task_id: str) -> None:
        """Reset circuit breaker for a task (after successful completion)."""
        self._recent_errors = [
            (tid, ts, sig) for tid, ts, sig in self._recent_errors
            if tid != task_id
        ]
        self._no_progress_count.pop(task_id, None)
    
    def get_error_signature(self, error: Exception | str) -> str:
        """Generate a stable signature for an error."""
        if isinstance(error, Exception):
            # Use exception type + first line of message
            return f"{type(error).__name__}:{str(error).split(chr(10))[0][:50]}"
        return str(error)[:100]
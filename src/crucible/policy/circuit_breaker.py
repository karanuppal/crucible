"""
Circuit breaker for Crucible v5.4.

Trips on:
- loop detection (repeated same symptom)
- repeated symptom recurrence
- budget exhaustion with no recovery path
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional


class CircuitState(str, Enum):
    """Circuit breaker states."""
    
    CLOSED = "closed"      # Normal operation
    OPEN = "open"          # Blocked, no more attempts
    HALF_OPEN = "half_open"  # Testing if recovery is possible


@dataclass
class CircuitBreakerConfig:
    """Configuration for circuit breaker behavior."""
    
    # How many identical failures before tripping
    failure_threshold: int = 3
    
    # How many attempts with no progress before tripping
    no_progress_threshold: int = 5
    
    # Time window to consider failures as "recent" (seconds)
    failure_window_seconds: int = 300
    
    # Whether to allow half-open recovery
    allow_half_open: bool = False


@dataclass
class CircuitBreaker:
    """
    Circuit breaker that trips when repeated failures detected.
    
    Once tripped, the runtime must block or escalate - no more auto-retries.
    """
    
    config: CircuitBreakerConfig = field(default_factory=CircuitBreakerConfig)
    state: CircuitState = CircuitState.CLOSED
    
    # Tracking state
    _failure_count: int = 0
    _no_progress_count: int = 0
    _last_failure_time: Optional[datetime] = None
    _last_failure_type: Optional[str] = None
    _opened_at: Optional[datetime] = None
    _open_reason: Optional[str] = None
    
    def record_failure(self, failure_type: str, symptom: str = "") -> bool:
        """
        Record a failure occurrence.
        
        Returns True if circuit remains closed, False if circuit trips.
        """
        now = datetime.utcnow()
        
        # Check if this is a repeated failure of the same type
        is_repeated = (
            self._last_failure_type == failure_type and
            self._last_failure_time is not None and
            (now - self._last_failure_time).total_seconds() < self.config.failure_window_seconds
        )
        
        if is_repeated:
            self._failure_count += 1
        else:
            self._failure_count = 1
        
        self._last_failure_time = now
        self._last_failure_type = failure_type
        
        # Check if we should trip
        if self._failure_count >= self.config.failure_threshold:
            self._trip(f"repeated {failure_type} failures ({self._failure_count})")
            return False
        
        return True
    
    def record_no_progress(self, reason: str = ""):
        """Record an attempt with no progress."""
        self._no_progress_count += 1
        
        if self._no_progress_count >= self.config.no_progress_threshold:
            self._trip(f"no progress after {self._no_progress_count} attempts: {reason}")
    
    def record_progress(self):
        """Record meaningful progress - resets no-progress counter."""
        self._no_progress_count = 0
    
    def can_continue(self) -> bool:
        """Check if runtime can continue (circuit not open)."""
        return self.state != CircuitState.OPEN
    
    def is_open(self) -> bool:
        """Check if circuit is open."""
        return self.state == CircuitState.OPEN
    
    def is_half_open(self) -> bool:
        """Check if circuit is half-open."""
        return self.state == CircuitState.HALF_OPEN
    
    def _trip(self, reason: str):
        """Trip the circuit breaker."""
        self.state = CircuitState.OPEN
        self._opened_at = datetime.utcnow()
        self._open_reason = reason
    
    def attempt_reset(self) -> bool:
        """
        Attempt to reset the circuit (half-open state).
        
        Returns True if reset successful, False if still open.
        """
        if not self.config.allow_half_open:
            return False
        
        if self.state == CircuitState.OPEN:
            self.state = CircuitState.HALF_OPEN
            return True
        
        if self.state == CircuitState.HALF_OPEN:
            # In half-open, a successful operation closes the circuit
            self.state = CircuitState.CLOSED
            self._failure_count = 0
            self._no_progress_count = 0
            self._opened_at = None
            self._open_reason = None
            return True
        
        return False
    
    def force_reset(self):
        """Force reset the circuit breaker."""
        self.state = CircuitState.CLOSED
        self._failure_count = 0
        self._no_progress_count = 0
        self._last_failure_time = None
        self._last_failure_type = None
        self._opened_at = None
        self._open_reason = None
    
    def get_status(self) -> dict:
        """Get circuit breaker status."""
        return {
            "state": self.state.value,
            "failure_count": self._failure_count,
            "no_progress_count": self._no_progress_count,
            "last_failure_type": self._last_failure_type,
            "opened_at": self._opened_at.isoformat() if self._opened_at else None,
            "open_reason": self._open_reason,
        }
    
    def get_open_reason(self) -> Optional[str]:
        """Get reason circuit is open."""
        if self.state == CircuitState.OPEN:
            return self._open_reason
        return None
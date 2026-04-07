"""
Tests for circuit breaker.

Phase 2: Budget Policy Engine
"""

import pytest

from crucible.policy.circuit_breaker import CircuitBreaker, CircuitBreakerConfig, CircuitState


class TestCircuitBreakerConfig:
    """Test CircuitBreakerConfig."""
    
    def test_defaults(self):
        """Default config has correct values."""
        config = CircuitBreakerConfig()
        
        assert config.failure_threshold == 3
        assert config.no_progress_threshold == 5
        assert config.failure_window_seconds == 300
        assert config.allow_half_open is False


class TestCircuitBreaker:
    """Test CircuitBreaker."""
    
    def test_initial_state_closed(self):
        """Circuit starts closed."""
        cb = CircuitBreaker()
        
        assert cb.state == CircuitState.CLOSED
        assert cb.can_continue() is True
        assert cb.is_open() is False
    
    def test_single_failure_doesnt_trip(self):
        """Single failure doesn't trip circuit."""
        cb = CircuitBreaker(CircuitBreakerConfig(failure_threshold=3))
        
        result = cb.record_failure("validation_failure")
        
        assert result is True
        assert cb.state == CircuitState.CLOSED
    
    def test_threshold_failures_trip(self):
        """Threshold failures trip circuit."""
        cb = CircuitBreaker(CircuitBreakerConfig(failure_threshold=2))
        
        cb.record_failure("validation_failure")
        result = cb.record_failure("validation_failure")
        
        assert result is False
        assert cb.state == CircuitState.OPEN
        assert cb.can_continue() is False
    
    def test_different_failure_types_count_separately(self):
        """Different failure types don't trigger threshold."""
        cb = CircuitBreaker(CircuitBreakerConfig(failure_threshold=2))
        
        cb.record_failure("validation_failure")
        cb.record_failure("environment_block")
        
        # Should not trip - different types
        assert cb.state == CircuitState.CLOSED
        assert cb._failure_count == 1
    
    def test_repeated_same_type_within_window(self):
        """Same failure type within window increments count."""
        cb = CircuitBreaker(CircuitBreakerConfig(failure_threshold=3, failure_window_seconds=60))
        
        cb.record_failure("validation_failure")
        cb.record_failure("validation_failure")
        
        assert cb._failure_count == 2
        assert cb.state == CircuitState.CLOSED
    
    def test_no_progress_threshold(self):
        """No progress threshold trips circuit."""
        cb = CircuitBreaker(CircuitBreakerConfig(no_progress_threshold=3))
        
        cb.record_no_progress("no output")
        cb.record_no_progress("same error")
        result = cb.record_no_progress("still failing")
        
        assert result is None  # record_no_progress doesn't return status
        assert cb.state == CircuitState.OPEN  # trips when threshold reached
        assert cb._no_progress_count == 3
    
    def test_record_progress_resets_no_progress(self):
        """record_progress resets no-progress counter."""
        cb = CircuitBreaker(CircuitBreakerConfig(no_progress_threshold=5))
        
        cb.record_no_progress("test")
        cb.record_no_progress("test")
        cb.record_progress()
        
        assert cb._no_progress_count == 0
    
    def test_open_reason_captured(self):
        """Open reason is captured when trip occurs."""
        cb = CircuitBreaker(CircuitBreakerConfig(failure_threshold=1))
        
        cb.record_failure("loop_detected", "infinite recursion")
        
        assert cb.get_open_reason() is not None
        assert "loop_detected" in cb.get_open_reason()
    
    def test_force_reset(self):
        """force_reset restores closed state."""
        cb = CircuitBreaker(CircuitBreakerConfig(failure_threshold=1))
        cb.record_failure("validation_failure")
        assert cb.state == CircuitState.OPEN
        
        cb.force_reset()
        
        assert cb.state == CircuitState.CLOSED
        assert cb._failure_count == 0
        assert cb.can_continue() is True
    
    def test_half_open_requires_config(self):
        """Half-open requires config enabled."""
        cb = CircuitBreaker(CircuitBreakerConfig(allow_half_open=False))
        
        cb.record_failure("validation_failure")  # trips
        result = cb.attempt_reset()
        
        assert result is False
    
    def test_half_open_with_config(self):
        """Half-open works when config enabled."""
        cb = CircuitBreaker(CircuitBreakerConfig(allow_half_open=True, failure_threshold=1))
        cb.record_failure("validation_failure")
        assert cb.state == CircuitState.OPEN
        
        result = cb.attempt_reset()
        
        assert result is True
        assert cb.state == CircuitState.HALF_OPEN
    
    def test_half_open_to_closed_on_progress(self):
        """Half-open transitions to closed on progress."""
        cb = CircuitBreaker(CircuitBreakerConfig(allow_half_open=True, failure_threshold=1))
        cb.record_failure("validation_failure")
        cb.attempt_reset()  # now half-open
        
        result = cb.attempt_reset()  # progress made
        
        assert result is True
        assert cb.state == CircuitState.CLOSED
    
    def test_get_status(self):
        """get_status returns full state."""
        cb = CircuitBreaker(CircuitBreakerConfig(failure_threshold=1))
        cb.record_failure("test_failure")
        
        status = cb.get_status()
        
        assert "state" in status
        assert "failure_count" in status
        assert status["failure_count"] == 1
    
    def test_cannot_continue_when_open(self):
        """can_continue returns False when open."""
        cb = CircuitBreaker(CircuitBreakerConfig(failure_threshold=1))
        cb.record_failure("validation_failure")
        
        assert cb.can_continue() is False
    
    def test_cannot_continue_when_half_open(self):
        """can_continue returns True in half-open (testing recovery)."""
        cb = CircuitBreaker(CircuitBreakerConfig(allow_half_open=True, failure_threshold=1))
        cb.record_failure("validation_failure")
        cb.attempt_reset()
        
        # Half-open allows attempts to test recovery
        assert cb.can_continue() is True
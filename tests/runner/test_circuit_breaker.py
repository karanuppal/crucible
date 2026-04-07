"""Phase 2 tests: Circuit breaker."""

import pytest
import time

from crucible.runner.circuit_breaker import CircuitBreaker, RejectionEntry


class TestCircuitBreakerTrip:
    def test_trips_on_repeated_same_error(self):
        cb = CircuitBreaker(error_threshold=2, window_seconds=60)
        task_id = "t1"
        
        cb.record_error(task_id, cb.get_error_signature(ValueError("same error")))
        cb.record_error(task_id, cb.get_error_signature(ValueError("same error")))
        
        assert cb.should_trip(task_id)
    
    def test_no_trip_on_different_errors(self):
        cb = CircuitBreaker(error_threshold=2, window_seconds=60)
        task_id = "t1"
        
        cb.record_error(task_id, cb.get_error_signature(ValueError("error 1")))
        cb.record_error(task_id, cb.get_error_signature(RuntimeError("error 2")))
        
        assert not cb.should_trip(task_id)
    
    def test_trips_on_no_progress(self):
        cb = CircuitBreaker(no_progress_threshold=2)
        task_id = "t1"
        
        cb.record_no_progress(task_id)
        cb.record_no_progress(task_id)
        
        assert cb.should_trip(task_id)


class TestRejectionLedger:
    def test_records_approach(self):
        cb = CircuitBreaker()
        cb.record_approach("t1", "approach_a", "failed", "evidence 1")
        
        rejections = cb.get_rejections("t1")
        assert len(rejections) == 1
        assert rejections[0].approach == "approach_a"
    
    def test_prevents_same_approach_retry(self):
        cb = CircuitBreaker(window_seconds=60)
        cb.record_approach("t1", "approach_a", "failed", "evidence 1")
        
        assert not cb.can_retry("t1", "approach_a")
    
    def test_allows_different_approach(self):
        cb = CircuitBreaker(window_seconds=60)
        cb.record_approach("t1", "approach_a", "failed", "evidence 1")
        
        assert cb.can_retry("t1", "approach_b")


class TestReset:
    def test_reset_clears_state(self):
        cb = CircuitBreaker(error_threshold=2)
        task_id = "t1"
        
        cb.record_error(task_id, "error")
        cb.record_no_progress(task_id)
        
        cb.reset(task_id)
        
        assert not cb.should_trip(task_id)
        assert cb.get_rejections(task_id) == []
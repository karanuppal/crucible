"""
Tests for attempt state enums.

Phase 1: Attempt State Machine & Data Models
"""

import pytest

from crucible.state.attempt_state import AttemptState


class TestAttemptState:
    """Test AttemptState enum and class methods."""
    
    def test_all_states_defined(self):
        """All expected states are defined."""
        expected_states = {
            "pending",
            "running",
            "completed_unverified",
            "validated_pass",
            "validated_fail",
            "partial",
            "blocked",
            "abandoned",
            "superseded",
        }
        actual_states = {s.value for s in AttemptState}
        assert actual_states == expected_states
    
    def test_terminal_states(self):
        """Terminal states are correctly identified."""
        terminal = AttemptState.terminal_states()
        assert AttemptState.VALIDATED_PASS in terminal
        assert AttemptState.BLOCKED in terminal
        assert AttemptState.ABANDONED in terminal
        assert AttemptState.SUPERSEDED in terminal
        
        # Active states should not be terminal
        assert AttemptState.PENDING not in terminal
        assert AttemptState.RUNNING not in terminal
        assert AttemptState.VALIDATED_FAIL not in terminal
    
    def test_active_states(self):
        """Active states are correctly identified."""
        active = AttemptState.active_states()
        assert AttemptState.PENDING in active
        assert AttemptState.RUNNING in active
        assert AttemptState.COMPLETED_UNVERIFIED in active
        assert AttemptState.VALIDATED_FAIL in active
        assert AttemptState.PARTIAL in active
        
        # Terminal states should not be active
        assert AttemptState.VALIDATED_PASS not in active
        assert AttemptState.BLOCKED not in active
    
    def test_is_terminal(self):
        """is_terminal returns correct boolean."""
        assert AttemptState.is_terminal(AttemptState.VALIDATED_PASS) is True
        assert AttemptState.is_terminal(AttemptState.BLOCKED) is True
        assert AttemptState.is_terminal(AttemptState.PENDING) is False
        assert AttemptState.is_terminal(AttemptState.RUNNING) is False
    
    def test_is_active(self):
        """is_active returns correct boolean."""
        assert AttemptState.is_active(AttemptState.PENDING) is True
        assert AttemptState.is_active(AttemptState.RUNNING) is True
        assert AttemptState.is_active(AttemptState.VALIDATED_PASS) is False
        assert AttemptState.is_active(AttemptState.BLOCKED) is False
    
    def test_terminal_and_active_disjoint(self):
        """Terminal and active states have no overlap."""
        terminal = AttemptState.terminal_states()
        active = AttemptState.active_states()
        assert terminal.isdisjoint(active)
    
    def test_all_states_covered(self):
        """Every state is either terminal or active."""
        all_states = set(AttemptState)
        terminal = AttemptState.terminal_states()
        active = AttemptState.active_states()
        covered = terminal.union(active)
        assert covered == all_states
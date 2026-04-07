"""
Tests for budget policy and tracker.

Phase 2: Budget Policy Engine
"""

import pytest

from crucible.policy.budgets import BudgetPolicy
from crucible.policy.budget_tracker import BudgetSpent, BudgetTracker
from crucible.state.attempt_type import AttemptType


class TestBudgetPolicy:
    """Test BudgetPolicy dataclass."""
    
    def test_default_values(self):
        """Default policy has correct values."""
        policy = BudgetPolicy.default()
        
        assert policy.spawn_retry_budget == 3
        assert policy.build_attempt_budget == 3
        assert policy.repair_attempt_budget == 5
        assert policy.debug_attempt_budget == 3
        assert policy.review_rejection_budget == 3
        assert policy.salvage_attempt_budget == 2
        assert policy.integration_budget == 3
    
    def test_to_dict(self):
        """to_dict produces correct structure."""
        policy = BudgetPolicy()
        d = policy.to_dict()
        
        assert "spawn_retry_budget" in d
        assert "repair_attempt_budget" in d
        assert d["repair_attempt_budget"] == 5
    
    def test_from_dict(self):
        """from_dict creates policy correctly."""
        data = {
            "spawn_retry_budget": 2,
            "build_attempt_budget": 4,
            "repair_attempt_budget": 6,
        }
        policy = BudgetPolicy.from_dict(data)
        
        assert policy.spawn_retry_budget == 2
        assert policy.build_attempt_budget == 4
        assert policy.repair_attempt_budget == 6
        # Defaults for missing keys
        assert policy.debug_attempt_budget == 3
    
    def test_reset(self):
        """reset restores defaults."""
        policy = BudgetPolicy(
            spawn_retry_budget=1,
            repair_attempt_budget=1,
        )
        policy.reset()
        
        assert policy.spawn_retry_budget == 3
        assert policy.repair_attempt_budget == 5


class TestBudgetSpent:
    """Test BudgetSpent tracking."""
    
    def test_initial_state(self):
        """Initial state has correct values."""
        spent = BudgetSpent(budget_type="test", total=5)
        
        assert spent.total == 5
        assert spent.spent == 0
        assert spent.remaining == 5
        assert spent.is_exhausted is False
    
    def test_consume_decrements(self):
        """consume reduces remaining."""
        spent = BudgetSpent(budget_type="test", total=3)
        
        result = spent.consume("test reason")
        
        assert result is True
        assert spent.spent == 1
        assert spent.remaining == 2
        assert spent.is_exhausted is False
    
    def test_exhaustion_at_limit(self):
        """Exhaustion triggers at exact limit."""
        spent = BudgetSpent(budget_type="test", total=2)
        
        spent.consume("first")
        assert spent.is_exhausted is False
        
        spent.consume("second")
        assert spent.is_exhausted is True
        assert spent.exhaustion_reason is not None
    
    def test_consume_when_exhausted(self):
        """Consume fails when exhausted."""
        spent = BudgetSpent(budget_type="test", total=1)
        spent.consume("first")
        
        result = spent.consume("second")
        
        assert result is False
        assert spent.spent == 1  # No additional spend
    
    def test_reset_restores(self):
        """reset restores budget to full."""
        spent = BudgetSpent(budget_type="test", total=5)
        spent.consume("test")
        spent.consume("test")
        
        spent.reset()
        
        assert spent.spent == 0
        assert spent.remaining == 5
        assert spent.is_exhausted is False


class TestBudgetTracker:
    """Test BudgetTracker."""
    
    def test_initialization(self):
        """Tracker initializes all budgets."""
        policy = BudgetPolicy()
        tracker = BudgetTracker(policy)
        
        assert tracker.get_remaining(AttemptType.BUILD) == 3
        assert tracker.get_remaining(AttemptType.REPAIR) == 5
        assert tracker.get_remaining(AttemptType.DEBUG) == 3
    
    def test_can_attempt_true(self):
        """can_attempt returns True when budget available."""
        policy = BudgetPolicy(repair_attempt_budget=1)
        tracker = BudgetTracker(policy)
        
        assert tracker.can_attempt(AttemptType.REPAIR) is True
    
    def test_can_attempt_false_when_exhausted(self):
        """can_attempt returns False when exhausted."""
        policy = BudgetPolicy(repair_attempt_budget=1)
        tracker = BudgetTracker(policy)
        tracker.consume(AttemptType.REPAIR, "test")
        
        assert tracker.can_attempt(AttemptType.REPAIR) is False
    
    def test_consume_returns_true_until_exhausted(self):
        """consume returns True until budget exhausted."""
        policy = BudgetPolicy(repair_attempt_budget=2)
        tracker = BudgetTracker(policy)
        
        assert tracker.consume(AttemptType.REPAIR, "first") is True
        assert tracker.consume(AttemptType.REPAIR, "second") is True
        assert tracker.consume(AttemptType.REPAIR, "third") is False
    
    def test_revalidate_uses_repair_budget(self):
        """REVALIDATE attempt type uses repair budget."""
        policy = BudgetPolicy(repair_attempt_budget=1)
        tracker = BudgetTracker(policy)
        
        assert tracker.consume(AttemptType.REVALIDATE, "test") is True
        # Now repair should also be exhausted (shares budget)
        assert tracker.consume(AttemptType.REPAIR, "test") is False
    
    def test_get_all_remaining(self):
        """get_all_remaining returns all budgets."""
        policy = BudgetPolicy()
        tracker = BudgetTracker(policy)
        
        remaining = tracker.get_all_remaining()
        
        assert "repair_attempt_budget" in remaining
        assert remaining["repair_attempt_budget"] == 5
    
    def test_get_exhaustion_status(self):
        """get_exhaustion_status shows exhaustion details."""
        policy = BudgetPolicy(repair_attempt_budget=1)
        tracker = BudgetTracker(policy)
        tracker.consume(AttemptType.REPAIR, "exhausted")
        
        status = tracker.get_exhaustion_status()
        
        assert status["repair_attempt_budget"]["exhausted"] is True
        assert status["repair_attempt_budget"]["remaining"] == 0
    
    def test_reset_specific_type(self):
        """reset can target specific attempt type."""
        policy = BudgetPolicy(repair_attempt_budget=1)
        tracker = BudgetTracker(policy)
        tracker.consume(AttemptType.REPAIR, "test")
        
        tracker.reset(AttemptType.REPAIR)
        
        assert tracker.get_remaining(AttemptType.REPAIR) == 1
    
    def test_is_exhausted(self):
        """is_exhausted returns correct state."""
        policy = BudgetPolicy(debug_attempt_budget=1)
        tracker = BudgetTracker(policy)
        
        assert tracker.is_exhausted(AttemptType.DEBUG) is False
        tracker.consume(AttemptType.DEBUG, "test")
        assert tracker.is_exhausted(AttemptType.DEBUG) is True
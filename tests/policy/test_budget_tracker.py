"""Tests for budget policy and tracker."""

from crucible.policy.budgets import BudgetPolicy
from crucible.policy.budget_tracker import BudgetSpent, BudgetTracker
from crucible.state.attempt_type import AttemptType


class TestBudgetPolicy:
    def test_default_values(self):
        policy = BudgetPolicy.default()
        assert policy.spawn_retry_budget == 3
        assert policy.build_attempt_budget == 3
        assert policy.repair_attempt_budget == 8
        assert policy.debug_attempt_budget == 4
        assert policy.review_rejection_budget == 3
        assert policy.salvage_attempt_budget == 4
        assert policy.integration_attempt_budget == 3
        assert policy.deep_recovery_budget == 6

    def test_to_dict(self):
        policy = BudgetPolicy()
        d = policy.to_dict()
        assert "spawn_retry_budget" in d
        assert "repair_attempt_budget" in d
        assert d["repair_attempt_budget"] == 8
        assert d["integration_attempt_budget"] == 3

    def test_from_dict(self):
        data = {
            "spawn_retry_budget": 2,
            "build_attempt_budget": 4,
            "repair_attempt_budget": 6,
            "integration_budget": 7,
        }
        policy = BudgetPolicy.from_dict(data)
        assert policy.spawn_retry_budget == 2
        assert policy.build_attempt_budget == 4
        assert policy.repair_attempt_budget == 6
        assert policy.integration_attempt_budget == 7
        assert policy.debug_attempt_budget == 4

    def test_reset(self):
        policy = BudgetPolicy(spawn_retry_budget=1, repair_attempt_budget=1)
        policy.reset()
        assert policy.spawn_retry_budget == 3
        assert policy.repair_attempt_budget == 8


class TestBudgetSpent:
    def test_initial_state(self):
        spent = BudgetSpent(budget_type="test", total=5)
        assert spent.total == 5
        assert spent.spent == 0
        assert spent.remaining == 5
        assert spent.is_exhausted is False

    def test_consume_decrements(self):
        spent = BudgetSpent(budget_type="test", total=3)
        result = spent.consume("test reason")
        assert result is True
        assert spent.spent == 1
        assert spent.remaining == 2
        assert spent.is_exhausted is False

    def test_exhaustion_at_limit(self):
        spent = BudgetSpent(budget_type="test", total=2)
        spent.consume("first")
        assert spent.is_exhausted is False
        spent.consume("second")
        assert spent.is_exhausted is True
        assert spent.exhaustion_reason is not None

    def test_consume_when_exhausted(self):
        spent = BudgetSpent(budget_type="test", total=1)
        spent.consume("first")
        result = spent.consume("second")
        assert result is False
        assert spent.spent == 1

    def test_reset_restores(self):
        spent = BudgetSpent(budget_type="test", total=5)
        spent.consume("test")
        spent.consume("test")
        spent.reset()
        assert spent.spent == 0
        assert spent.remaining == 5
        assert spent.is_exhausted is False


class TestBudgetTracker:
    def test_initialization(self):
        tracker = BudgetTracker(BudgetPolicy())
        assert tracker.get_remaining(AttemptType.BUILD) == 3
        assert tracker.get_remaining(AttemptType.REPAIR) == 8
        assert tracker.get_remaining(AttemptType.DEBUG) == 4

    def test_can_attempt_true(self):
        tracker = BudgetTracker(BudgetPolicy(repair_attempt_budget=1))
        assert tracker.can_attempt(AttemptType.REPAIR) is True

    def test_can_attempt_false_when_exhausted(self):
        tracker = BudgetTracker(BudgetPolicy(repair_attempt_budget=1))
        tracker.consume(AttemptType.REPAIR, "test")
        assert tracker.can_attempt(AttemptType.REPAIR) is False

    def test_consume_returns_true_until_exhausted(self):
        tracker = BudgetTracker(BudgetPolicy(repair_attempt_budget=2))
        assert tracker.consume(AttemptType.REPAIR, "first") is True
        assert tracker.consume(AttemptType.REPAIR, "second") is True
        assert tracker.consume(AttemptType.REPAIR, "third") is False

    def test_revalidate_uses_repair_budget(self):
        tracker = BudgetTracker(BudgetPolicy(repair_attempt_budget=1))
        assert tracker.consume(AttemptType.REVALIDATE, "test") is True
        assert tracker.consume(AttemptType.REPAIR, "test") is False

    def test_integrate_uses_integration_attempt_budget(self):
        tracker = BudgetTracker(BudgetPolicy(integration_attempt_budget=1))
        assert tracker.consume(AttemptType.INTEGRATE, "merge") is True
        assert tracker.consume(AttemptType.INTEGRATE, "merge-again") is False

    def test_get_all_remaining(self):
        tracker = BudgetTracker(BudgetPolicy())
        remaining = tracker.get_all_remaining()
        assert "repair_attempt_budget" in remaining
        assert remaining["repair_attempt_budget"] == 8
        assert remaining["deep_recovery_budget"] == 6

    def test_get_exhaustion_status(self):
        tracker = BudgetTracker(BudgetPolicy(repair_attempt_budget=1))
        tracker.consume(AttemptType.REPAIR, "exhausted")
        status = tracker.get_exhaustion_status()
        assert status["repair_attempt_budget"]["exhausted"] is True
        assert status["repair_attempt_budget"]["remaining"] == 0

    def test_reset_specific_type(self):
        tracker = BudgetTracker(BudgetPolicy(repair_attempt_budget=1))
        tracker.consume(AttemptType.REPAIR, "test")
        tracker.reset(AttemptType.REPAIR)
        assert tracker.get_remaining(AttemptType.REPAIR) == 1

    def test_is_exhausted(self):
        tracker = BudgetTracker(BudgetPolicy(debug_attempt_budget=1))
        assert tracker.is_exhausted(AttemptType.DEBUG) is False
        tracker.consume(AttemptType.DEBUG, "test")
        assert tracker.is_exhausted(AttemptType.DEBUG) is True

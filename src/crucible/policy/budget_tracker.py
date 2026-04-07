"""
Budget tracker for Crucible v5.4.

Tracks spent vs remaining per attempt type, enforces limits, records exhaustion.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from crucible.policy.budgets import BudgetPolicy
from crucible.state.attempt_type import AttemptType


@dataclass
class BudgetSpent:
    """Tracks spending for a single budget type."""
    
    budget_type: str
    total: int
    spent: int = 0
    last_spent_at: Optional[datetime] = None
    exhausted: bool = False
    exhaustion_reason: Optional[str] = None
    
    @property
    def remaining(self) -> int:
        """Returns remaining budget."""
        return max(0, self.total - self.spent)
    
    @property
    def is_exhausted(self) -> bool:
        """Check if budget is exhausted."""
        return self.exhausted or self.spent >= self.total
    
    def consume(self, reason: str = "") -> bool:
        """
        Attempt to consume one unit of budget.
        
        Returns True if successful, False if exhausted.
        """
        if self.is_exhausted:
            return False
        
        self.spent += 1
        self.last_spent_at = datetime.utcnow()
        
        if self.spent >= self.total:
            self.exhausted = True
            self.exhaustion_reason = reason
        
        return True
    
    def reset(self):
        """Reset this budget to full."""
        self.spent = 0
        self.last_spent_at = None
        self.exhausted = False
        self.exhaustion_reason = None


class BudgetTracker:
    """
    Tracks all budget types for a task/run.
    
    Provides deterministic enforcement of attempt limits.
    """
    
    # Map attempt types to their budget keys
    BUDGET_KEYS = {
        AttemptType.BUILD: "build_attempt_budget",
        AttemptType.REPAIR: "repair_attempt_budget",
        AttemptType.DEBUG: "debug_attempt_budget",
        AttemptType.REVIEW: "review_rejection_budget",
        AttemptType.SALVAGE: "salvage_attempt_budget",
        AttemptType.INTEGRATE: "integration_budget",
        AttemptType.REVALIDATE: "repair_attempt_budget",  # Revalidate uses repair budget
    }
    
    def __init__(self, policy: BudgetPolicy):
        """Initialize tracker with policy."""
        self.policy = policy
        self._budgets: dict[str, BudgetSpent] = {}
        self._initialize_budgets()
    
    def _initialize_budgets(self):
        """Initialize all budget tracking from policy."""
        policy_dict = self.policy.to_dict()
        for key, total in policy_dict.items():
            self._budgets[key] = BudgetSpent(
                budget_type=key,
                total=total,
            )
    
    def get_remaining(self, attempt_type: AttemptType) -> int:
        """Get remaining budget for an attempt type."""
        key = self.BUDGET_KEYS.get(attempt_type)
        if key not in self._budgets:
            return 0
        return self._budgets[key].remaining
    
    def get_all_remaining(self) -> dict[str, int]:
        """Get all remaining budgets as dict."""
        return {key: budget.remaining for key, budget in self._budgets.items()}
    
    def can_attempt(self, attempt_type: AttemptType) -> bool:
        """Check if an attempt type is still allowed."""
        remaining = self.get_remaining(attempt_type)
        return remaining > 0
    
    def consume(self, attempt_type: AttemptType, reason: str = "") -> bool:
        """
        Attempt to consume budget for an attempt type.
        
        Returns True if successful, False if exhausted.
        """
        key = self.BUDGET_KEYS.get(attempt_type)
        if key not in self._budgets:
            return False
        
        return self._budgets[key].consume(reason)
    
    def is_exhausted(self, attempt_type: AttemptType) -> bool:
        """Check if attempt type budget is exhausted."""
        key = self.BUDGET_KEYS.get(attempt_type)
        if key not in self._budgets:
            return True
        return self._budgets[key].is_exhausted
    
    def get_exhaustion_status(self) -> dict[str, dict]:
        """Get exhaustion status for all budgets."""
        return {
            key: {
                "remaining": budget.remaining,
                "exhausted": budget.exhausted,
                "exhaustion_reason": budget.exhaustion_reason,
            }
            for key, budget in self._budgets.items()
        }
    
    def reset(self, attempt_type: Optional[AttemptType] = None):
        """
        Reset budgets.
        
        If attempt_type provided, reset only that type.
        Otherwise reset all.
        """
        if attempt_type:
            key = self.BUDGET_KEYS.get(attempt_type)
            if key and key in self._budgets:
                self._budgets[key].reset()
        else:
            for budget in self._budgets.values():
                budget.reset()
    
    def get_budget_for_type(self, attempt_type: AttemptType) -> Optional[BudgetSpent]:
        """Get BudgetSpent object for an attempt type."""
        key = self.BUDGET_KEYS.get(attempt_type)
        if key:
            return self._budgets.get(key)
        return None
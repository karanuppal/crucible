"""
Budget policy for Crucible v5.4.

Replaces vague "retry count" with typed, bounded budgets per attempt type.
"""

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class BudgetPolicy:
    """
    Typed budgets for attempt limits.
    
    Each budget type is independent - exhausting repair budget doesn't
    affect debug budget, etc.
    """
    
    # Total allowed attempts per type
    spawn_retry_budget: int = 3
    build_attempt_budget: int = 3
    repair_attempt_budget: int = 5
    debug_attempt_budget: int = 3
    review_rejection_budget: int = 3
    salvage_attempt_budget: int = 2
    integration_budget: int = 3
    
    # Default values for easy reset
    DEFAULTS = {
        "spawn_retry_budget": 3,
        "build_attempt_budget": 3,
        "repair_attempt_budget": 5,
        "debug_attempt_budget": 3,
        "review_rejection_budget": 3,
        "salvage_attempt_budget": 2,
        "integration_budget": 3,
    }
    
    def to_dict(self) -> dict[str, int]:
        """Convert to dictionary for storage."""
        return {
            "spawn_retry_budget": self.spawn_retry_budget,
            "build_attempt_budget": self.build_attempt_budget,
            "repair_attempt_budget": self.repair_attempt_budget,
            "debug_attempt_budget": self.debug_attempt_budget,
            "review_rejection_budget": self.review_rejection_budget,
            "salvage_attempt_budget": self.salvage_attempt_budget,
            "integration_budget": self.integration_budget,
        }
    
    @classmethod
    def from_dict(cls, data: dict[str, int]) -> "BudgetPolicy":
        """Create from dictionary."""
        return cls(
            spawn_retry_budget=data.get("spawn_retry_budget", 3),
            build_attempt_budget=data.get("build_attempt_budget", 3),
            repair_attempt_budget=data.get("repair_attempt_budget", 5),
            debug_attempt_budget=data.get("debug_attempt_budget", 3),
            review_rejection_budget=data.get("review_rejection_budget", 3),
            salvage_attempt_budget=data.get("salvage_attempt_budget", 2),
            integration_budget=data.get("integration_budget", 3),
        )
    
    @classmethod
    def default(cls) -> "BudgetPolicy":
        """Create default policy."""
        return cls()
    
    def reset(self):
        """Reset all budgets to defaults."""
        self.spawn_retry_budget = self.DEFAULTS["spawn_retry_budget"]
        self.build_attempt_budget = self.DEFAULTS["build_attempt_budget"]
        self.repair_attempt_budget = self.DEFAULTS["repair_attempt_budget"]
        self.debug_attempt_budget = self.DEFAULTS["debug_attempt_budget"]
        self.review_rejection_budget = self.DEFAULTS["review_rejection_budget"]
        self.salvage_attempt_budget = self.DEFAULTS["salvage_attempt_budget"]
        self.integration_budget = self.DEFAULTS["integration_budget"]
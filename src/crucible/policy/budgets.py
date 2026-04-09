"""Budget policy for Crucible v6.1."""

from dataclasses import dataclass


@dataclass
class BudgetPolicy:
    """Typed budgets for attempt limits.

    Attempt budgets are role semantics; workers may still be LLM-backed.
    v6.1 also adds deep-recovery headroom for materially different retries.
    """

    spawn_retry_budget: int = 3
    build_attempt_budget: int = 3
    repair_attempt_budget: int = 8
    debug_attempt_budget: int = 4
    review_rejection_budget: int = 3
    salvage_attempt_budget: int = 4
    integration_attempt_budget: int = 3
    deep_recovery_budget: int = 6

    DEFAULTS = {
        "spawn_retry_budget": 3,
        "build_attempt_budget": 3,
        "repair_attempt_budget": 8,
        "debug_attempt_budget": 4,
        "review_rejection_budget": 3,
        "salvage_attempt_budget": 4,
        "integration_attempt_budget": 3,
        "deep_recovery_budget": 6,
    }

    @property
    def integration_budget(self) -> int:
        """Backward-compatible alias used by older code/tests."""
        return self.integration_attempt_budget

    def to_dict(self) -> dict[str, int]:
        return {
            "spawn_retry_budget": self.spawn_retry_budget,
            "build_attempt_budget": self.build_attempt_budget,
            "repair_attempt_budget": self.repair_attempt_budget,
            "debug_attempt_budget": self.debug_attempt_budget,
            "review_rejection_budget": self.review_rejection_budget,
            "salvage_attempt_budget": self.salvage_attempt_budget,
            "integration_attempt_budget": self.integration_attempt_budget,
            "deep_recovery_budget": self.deep_recovery_budget,
        }

    @classmethod
    def from_dict(cls, data: dict[str, int]) -> "BudgetPolicy":
        return cls(
            spawn_retry_budget=data.get("spawn_retry_budget", 3),
            build_attempt_budget=data.get("build_attempt_budget", 3),
            repair_attempt_budget=data.get("repair_attempt_budget", 8),
            debug_attempt_budget=data.get("debug_attempt_budget", 4),
            review_rejection_budget=data.get("review_rejection_budget", 3),
            salvage_attempt_budget=data.get("salvage_attempt_budget", 4),
            integration_attempt_budget=data.get("integration_attempt_budget", data.get("integration_budget", 3)),
            deep_recovery_budget=data.get("deep_recovery_budget", 6),
        )

    @classmethod
    def default(cls) -> "BudgetPolicy":
        return cls()

    def reset(self):
        self.spawn_retry_budget = self.DEFAULTS["spawn_retry_budget"]
        self.build_attempt_budget = self.DEFAULTS["build_attempt_budget"]
        self.repair_attempt_budget = self.DEFAULTS["repair_attempt_budget"]
        self.debug_attempt_budget = self.DEFAULTS["debug_attempt_budget"]
        self.review_rejection_budget = self.DEFAULTS["review_rejection_budget"]
        self.salvage_attempt_budget = self.DEFAULTS["salvage_attempt_budget"]
        self.integration_attempt_budget = self.DEFAULTS["integration_attempt_budget"]
        self.deep_recovery_budget = self.DEFAULTS["deep_recovery_budget"]

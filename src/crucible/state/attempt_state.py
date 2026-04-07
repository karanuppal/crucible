"""
Attempt state enumeration for Crucible v5.4.

Each task attempt has exactly one of these states.
"""

from enum import Enum


class AttemptState(str, Enum):
    """First-class attempt states in v5.4 closed-loop runtime."""
    
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED_UNVERIFIED = "completed_unverified"
    VALIDATED_PASS = "validated_pass"
    VALIDATED_FAIL = "validated_fail"
    PARTIAL = "partial"
    BLOCKED = "blocked"
    ABANDONED = "abandoned"
    SUPERSEDED = "superseded"
    
    @classmethod
    def terminal_states(cls) -> set["AttemptState"]:
        """States that represent task completion (no further auto-loop)."""
        return {
            cls.VALIDATED_PASS,
            cls.BLOCKED,
            cls.ABANDONED,
            cls.SUPERSEDED,
        }
    
    @classmethod
    def active_states(cls) -> set["AttemptState"]:
        """States that require runtime attention."""
        return {
            cls.PENDING,
            cls.RUNNING,
            cls.COMPLETED_UNVERIFIED,
            cls.VALIDATED_FAIL,
            cls.PARTIAL,
        }
    
    @classmethod
    def is_terminal(cls, state: "AttemptState") -> bool:
        """Check if state is terminal."""
        return state in cls.terminal_states()
    
    @classmethod
    def is_active(cls, state: "AttemptState") -> bool:
        """Check if state is active (needs attention)."""
        return state in cls.active_states()
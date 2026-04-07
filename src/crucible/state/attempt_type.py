"""
Attempt type enumeration for Crucible v5.4.

Each attempt is typed to enable deterministic handoff policy.
"""

from enum import Enum


class AttemptType(str, Enum):
    """
    Typed attempts replace vague 'retry' with explicit transitions.
    
    Key principle: retries are not generic. They are typed transitions.
    """
    
    BUILD = "build"           # Initial implementation attempt
    REPAIR = "repair"         # Fix after validation failure
    DEBUG = "debug"           # Diagnostic attempt when root cause unclear
    REVIEW = "review"         # Structured acceptance gate
    SALVAGE = "salvage"       # Extract value from partial artifacts
    INTEGRATE = "integrate"   # Merge multiple attempt outputs
    REVALIDATE = "revalidate" # Re-run validation on modified artifacts
    
    @classmethod
    def implementation_types(cls) -> set["AttemptType"]:
        """Attempt types that produce implementation artifacts."""
        return {
            cls.BUILD,
            cls.REPAIR,
            cls.DEBUG,
            cls.SALVAGE,
            cls.INTEGRATE,
        }
    
    @classmethod
    def validation_types(cls) -> set["AttemptType"]:
        """Attempt types that validate artifacts."""
        return {
            cls.REVIEW,
            cls.REVALIDATE,
        }
    
    @classmethod
    def is_implementation(cls, attempt_type: "AttemptType") -> bool:
        """Check if this is an implementation-generating attempt."""
        return attempt_type in cls.implementation_types()
    
    @classmethod
    def is_validation(cls, attempt_type: "AttemptType") -> bool:
        """Check if this is a validation-focused attempt."""
        return attempt_type in cls.validation_types()
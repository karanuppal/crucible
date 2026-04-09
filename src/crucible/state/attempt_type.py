"""
Attempt type enumeration for Crucible v6.1.

Attempt types describe the role/phase of a pass through the loop.
They are not "LLM vs non-LLM" lanes; any core attempt type may use an LLM worker.
"""

from enum import Enum


class AttemptType(str, Enum):
    BUILD = "build"
    REPAIR = "repair"
    DEBUG = "debug"
    REVIEW = "review"
    SALVAGE = "salvage"
    INTEGRATE = "integrate"
    REVALIDATE = "revalidate"

    @classmethod
    def implementation_types(cls) -> set["AttemptType"]:
        return {
            cls.BUILD,
            cls.REPAIR,
            cls.DEBUG,
            cls.SALVAGE,
            cls.INTEGRATE,
        }

    @classmethod
    def validation_types(cls) -> set["AttemptType"]:
        return {
            cls.REVIEW,
            cls.REVALIDATE,
        }

    @classmethod
    def llm_capable_types(cls) -> set["AttemptType"]:
        return set(cls)

    @classmethod
    def is_implementation(cls, attempt_type: "AttemptType") -> bool:
        return attempt_type in cls.implementation_types()

    @classmethod
    def is_validation(cls, attempt_type: "AttemptType") -> bool:
        return attempt_type in cls.validation_types()

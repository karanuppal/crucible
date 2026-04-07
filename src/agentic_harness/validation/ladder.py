"""Phase 3: Validation ladder — verification levels.

Spec §11: Validation escalates through rungs:
  NONE → STATIC → UNIT → INTEGRATION → END_TO_END

Each rung is strictly higher than the previous. Rungs are ordered by numeric rank,
NOT lexicographic string comparison (which would be a real logic bug).
"""

from __future__ import annotations

from enum import IntEnum


class LadderRung(IntEnum):
    """Validation rungs with explicit numeric rank for correct ordering."""
    NONE = 0
    STATIC = 1         # Type checks, lint, format
    UNIT = 2           # Unit tests
    INTEGRATION = 3    # Integration tests
    END_TO_END = 4     # Full system tests
    
    def is_at_least(self, other: "LadderRung") -> bool:
        return int(self) >= int(other)
    
    def is_higher_than(self, other: "LadderRung") -> bool:
        return int(self) > int(other)


def next_rung(current: LadderRung) -> LadderRung | None:
    """Return the next higher rung, or None if already at END_TO_END."""
    if current == LadderRung.END_TO_END:
        return None
    return LadderRung(int(current) + 1)


def required_rung_for_task_size(size: str) -> LadderRung:
    """Minimum rung required for a task size."""
    mapping = {
        "S": LadderRung.UNIT,
        "M": LadderRung.INTEGRATION,
        "L": LadderRung.END_TO_END,
    }
    return mapping.get(size, LadderRung.UNIT)

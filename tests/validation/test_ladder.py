"""Phase 3 tests: Ladder ordering (numeric, not lexicographic)."""

import pytest

from crucible.validation.ladder import (
    LadderRung, next_rung, required_rung_for_task_size,
)


class TestLadderOrdering:
    def test_numeric_not_lexicographic(self):
        """INTEGRATION > END_TO_END lexicographically (I > E) but not numerically."""
        # Numeric: END_TO_END (4) > INTEGRATION (3)
        assert LadderRung.END_TO_END.is_higher_than(LadderRung.INTEGRATION)
        assert not LadderRung.INTEGRATION.is_higher_than(LadderRung.END_TO_END)
    
    def test_all_pairs_correct(self):
        order = [
            LadderRung.NONE,
            LadderRung.STATIC,
            LadderRung.UNIT,
            LadderRung.INTEGRATION,
            LadderRung.END_TO_END,
        ]
        for i, lower in enumerate(order):
            for j, higher in enumerate(order):
                if j > i:
                    assert higher.is_higher_than(lower), f"{higher} should be > {lower}"
    
    def test_is_at_least(self):
        assert LadderRung.UNIT.is_at_least(LadderRung.UNIT)
        assert LadderRung.INTEGRATION.is_at_least(LadderRung.UNIT)
        assert not LadderRung.STATIC.is_at_least(LadderRung.UNIT)


class TestNextRung:
    def test_next_rung_progression(self):
        assert next_rung(LadderRung.NONE) == LadderRung.STATIC
        assert next_rung(LadderRung.STATIC) == LadderRung.UNIT
        assert next_rung(LadderRung.UNIT) == LadderRung.INTEGRATION
        assert next_rung(LadderRung.INTEGRATION) == LadderRung.END_TO_END
    
    def test_next_rung_at_top_returns_none(self):
        assert next_rung(LadderRung.END_TO_END) is None


class TestTaskSizeMapping:
    def test_small_task_unit(self):
        assert required_rung_for_task_size("S") == LadderRung.UNIT
    
    def test_medium_task_integration(self):
        assert required_rung_for_task_size("M") == LadderRung.INTEGRATION
    
    def test_large_task_end_to_end(self):
        assert required_rung_for_task_size("L") == LadderRung.END_TO_END

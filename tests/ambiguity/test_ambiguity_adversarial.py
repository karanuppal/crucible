"""Phase 1 adversarial tests: unknown severity, DEFER outcome."""

import pytest

from crucible.ambiguity.gate import (
    AmbiguityOutcome, AmbiguityCategory, AmbiguityFinding,
    classify_ambiguity,
)


class TestUnknownSeverity:
    """Unknown severity must NOT produce CLEAR."""

    def test_critical_severity_not_clear(self):
        findings = [
            AmbiguityFinding(
                category=AmbiguityCategory.MISSING_CRITERIA,
                description="No acceptance criteria",
                severity="critical",
            ),
        ]
        result = classify_ambiguity(findings)
        assert result.outcome != AmbiguityOutcome.CLEAR
        assert not result.is_safe_to_proceed()

    def test_unknown_severity_string_not_clear(self):
        findings = [
            AmbiguityFinding(
                category=AmbiguityCategory.CONTRADICTIONS,
                description="Something weird",
                severity="banana",
            ),
        ]
        result = classify_ambiguity(findings)
        assert result.outcome != AmbiguityOutcome.CLEAR
        assert not result.is_safe_to_proceed()

    def test_empty_severity_not_clear(self):
        findings = [
            AmbiguityFinding(
                category=AmbiguityCategory.HIDDEN_DEPENDENCIES,
                description="Unknown dep",
                severity="",
            ),
        ]
        result = classify_ambiguity(findings)
        assert result.outcome != AmbiguityOutcome.CLEAR


class TestDeferOutcome:
    """DEFER should be a valid output (contract completeness)."""

    def test_defer_is_valid_enum(self):
        assert AmbiguityOutcome.DEFER.value == "DEFER"

    def test_defer_result_not_safe(self):
        from crucible.ambiguity.gate import AmbiguityResult
        result = AmbiguityResult(outcome=AmbiguityOutcome.DEFER, rationale="Needs more info")
        assert not result.is_safe_to_proceed()

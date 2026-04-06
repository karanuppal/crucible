"""Phase 1 validation: Ambiguity gate tests.

Validation matrix requirements:
- Curated corpus produces correct outputs
- Adversarial cases that look clear but hide issues
- False-positive test: clearly specified input must not be over-classified
- Deterministic re-run yields stable output
"""

import pytest

from agentic_harness.ambiguity.gate import (
    AmbiguityOutcome, AmbiguityCategory, AmbiguityFinding,
    AmbiguityResult, classify_ambiguity,
)


class TestClearCases:
    """Clearly specified inputs should produce CLEAR."""

    def test_no_findings_is_clear(self):
        result = classify_ambiguity([])
        assert result.outcome == AmbiguityOutcome.CLEAR
        assert result.is_safe_to_proceed()

    def test_only_low_severity_is_clear(self):
        findings = [
            AmbiguityFinding(
                category=AmbiguityCategory.UNCLEAR_SCOPE,
                description="Minor scope ambiguity",
                severity="low",
            ),
        ]
        result = classify_ambiguity(findings)
        assert result.outcome == AmbiguityOutcome.CLEAR
        assert result.is_safe_to_proceed()

    def test_multiple_low_severity_still_clear(self):
        findings = [
            AmbiguityFinding(AmbiguityCategory.UNCLEAR_SCOPE, "Minor 1", "low"),
            AmbiguityFinding(AmbiguityCategory.UNDEFINED_TERMS, "Minor 2", "low"),
            AmbiguityFinding(AmbiguityCategory.MISSING_CRITERIA, "Minor 3", "low"),
        ]
        result = classify_ambiguity(findings)
        assert result.outcome == AmbiguityOutcome.CLEAR


class TestClarifyCases:
    """Ambiguous inputs should produce CLARIFY."""

    def test_high_severity_triggers_clarify(self):
        findings = [
            AmbiguityFinding(
                category=AmbiguityCategory.MISSING_CRITERIA,
                description="No acceptance criteria defined",
                severity="high",
                suggestion="What does 'working' mean for this feature?",
            ),
        ]
        result = classify_ambiguity(findings)
        assert result.outcome == AmbiguityOutcome.CLARIFY
        assert not result.is_safe_to_proceed()
        assert "What does" in result.clarificationQuestions[0]

    def test_single_medium_triggers_clarify(self):
        findings = [
            AmbiguityFinding(
                AmbiguityCategory.HIDDEN_DEPENDENCIES,
                "Depends on external API not mentioned",
                "medium",
            ),
        ]
        result = classify_ambiguity(findings)
        assert result.outcome == AmbiguityOutcome.CLARIFY

    def test_multiple_medium_same_category_triggers_clarify(self):
        findings = [
            AmbiguityFinding(AmbiguityCategory.MISSING_CRITERIA, "Missing A", "medium"),
            AmbiguityFinding(AmbiguityCategory.MISSING_CRITERIA, "Missing B", "medium"),
        ]
        result = classify_ambiguity(findings)
        assert result.outcome == AmbiguityOutcome.CLARIFY  # same category = CLARIFY not SPLIT


class TestSplitCases:
    """Multi-category medium issues should produce SPLIT."""

    def test_multiple_medium_different_categories_triggers_split(self):
        findings = [
            AmbiguityFinding(AmbiguityCategory.MISSING_CRITERIA, "Missing criteria", "medium"),
            AmbiguityFinding(AmbiguityCategory.UNCLEAR_SCOPE, "Unclear scope", "medium"),
        ]
        result = classify_ambiguity(findings)
        assert result.outcome == AmbiguityOutcome.SPLIT
        assert not result.is_safe_to_proceed()

    def test_three_categories_triggers_split(self):
        findings = [
            AmbiguityFinding(AmbiguityCategory.MISSING_CRITERIA, "A", "medium"),
            AmbiguityFinding(AmbiguityCategory.UNCLEAR_SCOPE, "B", "medium"),
            AmbiguityFinding(AmbiguityCategory.CONTRADICTIONS, "C", "medium"),
        ]
        result = classify_ambiguity(findings)
        assert result.outcome == AmbiguityOutcome.SPLIT


class TestAdversarialCases:
    """Cases that look clear but hide issues."""

    def test_looks_clear_but_has_hidden_dependency(self):
        """A request that sounds simple but depends on an unmentioned service."""
        findings = [
            AmbiguityFinding(
                category=AmbiguityCategory.HIDDEN_DEPENDENCIES,
                description="Request says 'fetch user data' but doesn't specify which API or auth method",
                severity="high",
                suggestion="Which user data source? What authentication is required?",
            ),
        ]
        result = classify_ambiguity(findings)
        assert result.outcome == AmbiguityOutcome.CLARIFY
        assert not result.is_safe_to_proceed()

    def test_looks_clear_but_contradicts(self):
        findings = [
            AmbiguityFinding(
                category=AmbiguityCategory.CONTRADICTIONS,
                description="Spec says 'real-time' but also 'batch processing daily'",
                severity="high",
            ),
        ]
        result = classify_ambiguity(findings)
        assert result.outcome == AmbiguityOutcome.CLARIFY


class TestFalsePositivePrevention:
    """Well-specified inputs must NOT be over-classified as ambiguous."""

    def test_clear_spec_not_over_classified(self):
        # No findings = no ambiguity
        result = classify_ambiguity([])
        assert result.outcome == AmbiguityOutcome.CLEAR

    def test_low_observations_dont_block(self):
        findings = [
            AmbiguityFinding(AmbiguityCategory.UNCLEAR_SCOPE, "Could be clearer", "low"),
        ]
        result = classify_ambiguity(findings)
        assert result.is_safe_to_proceed()


class TestDeterminism:
    """Same input must produce same output across runs."""

    def test_stable_output(self):
        findings = [
            AmbiguityFinding(AmbiguityCategory.MISSING_CRITERIA, "Missing X", "high", "Define X"),
        ]
        r1 = classify_ambiguity(findings)
        r2 = classify_ambiguity(findings)
        assert r1.outcome == r2.outcome
        assert r1.rationale == r2.rationale
        assert r1.clarificationQuestions == r2.clarificationQuestions


class TestCategoryDetection:
    """AmbiguityResult.has_category should work correctly."""

    def test_has_category(self):
        findings = [
            AmbiguityFinding(AmbiguityCategory.CONTRADICTIONS, "X contradicts Y", "high"),
        ]
        result = classify_ambiguity(findings)
        assert result.has_category(AmbiguityCategory.CONTRADICTIONS)
        assert not result.has_category(AmbiguityCategory.UNDEFINED_TERMS)

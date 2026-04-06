"""Phase 1: Ambiguity gate outputs and classification.

From the spec:
- Output format: CLEAR, CLARIFY, SPLIT, DEFER
- Analysis categories: undefined terms, missing criteria, unclear scope,
  hidden dependencies, contradictions
- The gate does NOT call an LLM in Phase 1 — it defines the output contract,
  fixture format, and classification structure.
- Actual LLM-backed analysis is a later integration concern.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class AmbiguityOutcome(str, Enum):
    CLEAR = "CLEAR"
    CLARIFY = "CLARIFY"
    SPLIT = "SPLIT"
    DEFER = "DEFER"


class AmbiguityCategory(str, Enum):
    UNDEFINED_TERMS = "undefined_terms"
    MISSING_CRITERIA = "missing_criteria"
    UNCLEAR_SCOPE = "unclear_scope"
    HIDDEN_DEPENDENCIES = "hidden_dependencies"
    CONTRADICTIONS = "contradictions"


@dataclass
class AmbiguityFinding:
    category: AmbiguityCategory
    description: str
    severity: str = "medium"  # low, medium, high
    suggestion: str = ""


@dataclass
class AmbiguityResult:
    outcome: AmbiguityOutcome
    findings: list[AmbiguityFinding] = field(default_factory=list)
    clarificationQuestions: list[str] = field(default_factory=list)
    rationale: str = ""

    def is_safe_to_proceed(self) -> bool:
        """Whether the harness can proceed to implementation."""
        return self.outcome == AmbiguityOutcome.CLEAR

    def has_category(self, category: AmbiguityCategory) -> bool:
        return any(f.category == category for f in self.findings)


def classify_ambiguity(findings: list[AmbiguityFinding]) -> AmbiguityResult:
    """Classify ambiguity based on findings.
    
    Rules:
    - No findings → CLEAR
    - Any high-severity finding → CLARIFY
    - Multiple medium-severity findings across different categories → SPLIT
    - Single medium finding → CLARIFY
    - Only low-severity findings → CLEAR (with observations)
    """
    if not findings:
        return AmbiguityResult(
            outcome=AmbiguityOutcome.CLEAR,
            rationale="No ambiguity detected.",
        )

    high = [f for f in findings if f.severity == "high"]
    medium = [f for f in findings if f.severity == "medium"]
    low = [f for f in findings if f.severity == "low"]

    if high:
        questions = [f.suggestion for f in high if f.suggestion]
        return AmbiguityResult(
            outcome=AmbiguityOutcome.CLARIFY,
            findings=findings,
            clarificationQuestions=questions,
            rationale=f"Found {len(high)} high-severity ambiguity issue(s).",
        )

    if len(medium) >= 2:
        categories = {f.category for f in medium}
        if len(categories) >= 2:
            return AmbiguityResult(
                outcome=AmbiguityOutcome.SPLIT,
                findings=findings,
                rationale=f"Found {len(medium)} medium-severity issues across {len(categories)} categories. Consider splitting the request.",
            )

    if medium:
        questions = [f.suggestion for f in medium if f.suggestion]
        return AmbiguityResult(
            outcome=AmbiguityOutcome.CLARIFY,
            findings=findings,
            clarificationQuestions=questions,
            rationale=f"Found {len(medium)} medium-severity ambiguity issue(s).",
        )

    # Only low-severity
    return AmbiguityResult(
        outcome=AmbiguityOutcome.CLEAR,
        findings=findings,
        rationale=f"Found {len(low)} low-severity observation(s). Safe to proceed.",
    )

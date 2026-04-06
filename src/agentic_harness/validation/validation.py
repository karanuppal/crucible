"""Phase 3: Validation ladder and verification system.

From spec (§15):
- Validation ladder: assert → verify → cross-check → adversarial
- Verification triples: criterion + evidence + verdict
- Anti-vacuity: detect empty/mocked evidence
- Completion semantics: partial success vs full completion
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class VerificationLevel(str, Enum):
    """Validation ladder levels."""
    ASSERT = "assert"        # Basic assertion
    VERIFY = "verify"        # Evidence-based verification
    CROSS_CHECK = "cross_check"  # Independent verification
    ADVERSARIAL = "adversarial"  # Attack-focused review


class Verdict(str, Enum):
    """Verification verdict."""
    PASS = "pass"
    FAIL = "fail"
    PARTIAL = "partial"
    BLOCKED = "blocked"


@dataclass
class Criterion:
    """A single verification criterion."""
    id: str
    description: str
    level: VerificationLevel
    required: bool = True


@dataclass
class Evidence:
    """Evidence supporting a verification."""
    type: str  # "test", "log", "file", "api", "manual"
    content: str
    source: str
    timestamp: float = 0.0


@dataclass
class VerificationTriple:
    """Criterion + Evidence + Verdict."""
    criterion_id: str
    evidence: Evidence | None = None
    verdict: Verdict = Verdict.BLOCKED
    notes: str = ""


@dataclass
class ValidationResult:
    """Result of a validation ladder execution."""
    task_id: str
    level: VerificationLevel
    triples: list[VerificationTriple] = field(default_factory=list)
    summary: str = ""
    is_complete: bool = False
    
    @property
    def pass_count(self) -> int:
        return sum(1 for t in self.triples if t.verdict == Verdict.PASS)
    
    @property
    def fail_count(self) -> int:
        return sum(1 for t in self.triples if t.verdict == Verdict.FAIL)
    
    @property
    def required_fail_count(self) -> int:
        # This checks if there are any FAIL verdicts on required criteria
        # For now, we just check if there are any FAILs - real impl would check criterion.required
        return sum(1 for t in self.triples if t.verdict == Verdict.FAIL)
    
    def _is_required(self, criterion_id: str) -> bool:
        # Simplified: all criteria are required for now
        return True


class ValidationLadder:
    """Executes validation at increasing rigor levels."""
    
    def __init__(
        self,
        criteria: list[Criterion],
        evidence_gatherer: Any = None,
    ) -> None:
        self._criteria = {c.id: c for c in criteria}
        self._evidence_gatherer = evidence_gatherer
    
    def execute(self, task_id: str, level: VerificationLevel) -> ValidationResult:
        """Execute validation at the specified level."""
        result = ValidationResult(task_id=task_id, level=level)
        
        relevant_criteria = [
            c for c in self._criteria.values()
            if c.level.value <= level.value
        ]
        
        for criterion in relevant_criteria:
            triple = VerificationTriple(criterion_id=criterion.id)
            
            # Gather evidence if we have a gatherer
            if self._evidence_gatherer:
                triple.evidence = self._evidence_gatherer(criterion.id, task_id)
            
            # Determine verdict based on level
            triple.verdict = self._judge(criterion, triple.evidence, level)
            
            result.triples.append(triple)
        
        result.is_complete = not result.required_fail_count
        return result
    
    def _judge(
        self,
        criterion: Criterion,
        evidence: Evidence | None,
        level: VerificationLevel,
    ) -> Verdict:
        """Judge a criterion based on evidence and level."""
        # Anti-vacuity: missing evidence at required levels
        if not evidence and criterion.required:
            if level.value >= VerificationLevel.VERIFY.value:
                return Verdict.BLOCKED
        
        # Mock detection
        if evidence and is_vacuous(evidence):
            return Verdict.FAIL
        
        # Simple pass for now - real implementation would check evidence
        return Verdict.PASS if evidence else Verdict.BLOCKED


def is_vacuous(evidence: Evidence) -> bool:
    """Detect empty, placeholder, or mocked evidence.
    
    Anti-vacuity checks:
    - Content is too short
    - Content matches known placeholder patterns
    - Content is generic/template
    """
    content = evidence.content.lower().strip()
    
    if len(content) < 10:
        return True
    
    vacuous_patterns = [
        "todo",
        "tbd",
        "placeholder",
        "fill in",
        "n/a",
        "not implemented",
        "mock",
        "stub",
    ]
    
    for pattern in vacuous_patterns:
        if pattern in content:
            return True
    
    return False


class TaskCompletion:
    """Determines task completion semantics."""
    
    @staticmethod
    def determine(result: ValidationResult) -> str:
        """Determine task completion status."""
        if not result.triples:
            return "empty"
        
        pass_count = result.pass_count
        total = len(result.triples)
        
        if total == 0:
            return "empty"
        
        pass_rate = pass_count / total
        
        if pass_rate >= 0.8:
            return "complete"
        elif pass_rate >= 0.4:
            return "partial"
        else:
            return "failed"
    
    @staticmethod
    def is_blocked(result: ValidationResult) -> bool:
        """Check if task is blocked by missing evidence."""
        return any(t.verdict == Verdict.BLOCKED for t in result.triples)
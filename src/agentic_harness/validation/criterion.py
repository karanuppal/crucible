"""Phase 3: Acceptance criterion and verification triple.

Spec §11/§12.3: Each task declares criteria. Each criterion is either must-pass or informational.
Execution Plan: Verification triple = (build target, verification command, expected output)
plus failure signature. No criterion can be signed off without executable evidence.
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Any

from agentic_harness.validation.artifact import ArtifactRef


class CriterionClass(str, Enum):
    """Classification per spec §12.3."""
    MUST_PASS = "must_pass"      # Blocks completion if fails
    INFORMATIONAL = "informational"  # Does not block, just informs


class CriterionVerdict(str, Enum):
    PASS = "pass"
    FAIL = "fail"
    BLOCKED = "blocked"  # Could not run (e.g., missing dependency)
    PENDING = "pending"  # Not yet evaluated


@dataclass
class VerificationTriple:
    """The verification contract for a criterion.
    
    A triple specifies EXACTLY how to verify a criterion:
    - build_target: what must exist/be buildable
    - verification_command: exact command to run
    - expected_output: what success looks like (substring or regex)
    - failure_signature: what known failure looks like
    """
    build_target: str  # e.g., "src/module.py" or "pytest tests/"
    verification_command: str  # e.g., "pytest tests/test_foo.py -v"
    expected_output: str  # e.g., "PASSED" or regex
    failure_signature: str = ""  # e.g., "FAILED" or "AssertionError"
    
    def is_well_formed(self) -> bool:
        """A triple must have non-empty build target, command, and expected output."""
        return bool(
            self.build_target.strip() and
            self.verification_command.strip() and
            self.expected_output.strip()
        )


@dataclass
class Criterion:
    """A single acceptance criterion with executable verification."""
    criterion_id: str
    description: str
    criterion_class: CriterionClass
    triple: VerificationTriple
    
    def to_dict(self) -> dict[str, Any]:
        return {
            "criterion_id": self.criterion_id,
            "description": self.description,
            "criterion_class": self.criterion_class.value,
            "triple": asdict(self.triple),
        }
    
    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Criterion":
        return cls(
            criterion_id=data["criterion_id"],
            description=data["description"],
            criterion_class=CriterionClass(data["criterion_class"]),
            triple=VerificationTriple(**data["triple"]),
        )


@dataclass
class CriterionResult:
    """The result of evaluating a criterion against evidence."""
    criterion_id: str
    verdict: CriterionVerdict
    evidence_artifacts: list[ArtifactRef] = field(default_factory=list)
    actual_output: str = ""
    error: str = ""
    
    def is_passing(self) -> bool:
        return self.verdict == CriterionVerdict.PASS
    
    def has_real_evidence(self) -> bool:
        """PASS verdict requires at least one reachable artifact."""
        if not self.evidence_artifacts:
            return False
        return all(a.exists() for a in self.evidence_artifacts)

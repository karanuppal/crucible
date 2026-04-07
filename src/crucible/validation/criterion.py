"""Phase 3: Acceptance criterion and verification triple.

Spec §11/§12.3: Each task declares criteria. Each criterion is either must-pass or informational.
Execution Plan: Verification triple = (build target, verification command, expected output)
plus failure signature. No criterion can be signed off without executable evidence.
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Any

from crucible.validation.artifact import ArtifactRef


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
    """The result of evaluating a criterion against evidence.
    
    Evidence provenance requirements (to prevent recycled-artifact attacks):
    - executed_command: the exact command that ran
    - run_id: which run produced the evidence
    - evidence_artifacts: all must be produced by run_id (checked via producer_run_id)
    """
    criterion_id: str
    verdict: CriterionVerdict
    evidence_artifacts: list[ArtifactRef] = field(default_factory=list)
    actual_output: str = ""
    error: str = ""
    executed_command: str = ""  # provenance: command that produced evidence
    run_id: str = ""  # provenance: which run produced this result
    
    def is_passing(self) -> bool:
        return self.verdict == CriterionVerdict.PASS
    
    def has_real_evidence(self, expected_command: str = "", expected_run_id: str = "") -> bool:
        """PASS verdict requires:
        1. At least one artifact
        2. All artifacts reachable AND integrity-verified
        3. If expected_command given: executed_command must match
        4. If expected_run_id given: run_id must match AND all artifacts from that run
        """
        if not self.evidence_artifacts:
            return False
        # Integrity check (not just existence)
        if not all(a.exists() and a.verify_integrity() for a in self.evidence_artifacts):
            return False
        # Command provenance
        if expected_command and self.executed_command != expected_command:
            return False
        # Run provenance: result must be tagged with run_id AND all artifacts from same run
        if expected_run_id:
            if self.run_id != expected_run_id:
                return False
            if not all(a.producer_run_id == expected_run_id for a in self.evidence_artifacts):
                return False
        elif self.run_id:
            # Even without expected, if run_id is set, all artifacts should match
            if not all(a.producer_run_id == self.run_id for a in self.evidence_artifacts):
                return False
        return True

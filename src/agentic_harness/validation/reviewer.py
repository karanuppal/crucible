"""Phase 3: Reviewer harness.

Spec §9.9 + §13: Reviewers are context-isolated from builders.
- Reviewer sees: spec, diffs, artifact refs, validation outputs
- Reviewer does NOT see: builder rationale, builder's chain of thought

Reviewer must produce a structured report with:
- Covered criteria (which were actually reviewed)
- Missing evidence (gaps)
- Untested critical branches (adversarial thinking)
- Escaped defect risk
- Verdict
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Any

from agentic_harness.validation.artifact import ArtifactRef


class ReviewerVerdict(str, Enum):
    APPROVE = "approve"
    REJECT = "reject"
    BLOCKED = "blocked"  # cannot assess


# Whitelist of fields a reviewer is allowed to see
ALLOWED_REVIEWER_INPUT_KEYS = {
    "spec",
    "criteria",
    "triples",
    "artifact_refs",
    "validation_verdict",
    "diffs",
}

# Explicitly forbidden fields (builder-private)
FORBIDDEN_REVIEWER_INPUT_KEYS = {
    "builder_rationale",
    "builder_thoughts",
    "builder_chain_of_thought",
    "builder_internal_notes",
}


@dataclass
class ReviewerInput:
    """The sanitized input a reviewer sees.
    
    Construction enforces that forbidden keys are never passed in.
    """
    spec: str
    criteria: list[dict[str, Any]]
    artifact_refs: list[ArtifactRef]
    validation_verdict: dict[str, Any]
    diffs: str = ""
    
    @classmethod
    def from_raw(cls, raw: dict[str, Any]) -> "ReviewerInput":
        """Build from raw dict, recursively rejecting forbidden keys at any depth."""
        validate_reviewer_input(raw)
        
        return cls(
            spec=raw["spec"],
            criteria=raw["criteria"],
            artifact_refs=raw.get("artifact_refs", []),
            validation_verdict=raw.get("validation_verdict", {}),
            diffs=raw.get("diffs", ""),
        )


@dataclass
class ReviewerReport:
    """Structured reviewer output.
    
    Machine-checkable schema — all fields required.
    """
    task_id: str
    reviewer_run_id: str
    covered_criteria: list[str]
    missing_evidence: list[str]
    untested_critical_branches: list[str]
    escaped_defect_risk: str  # description of risk
    verdict: ReviewerVerdict
    rationale: str
    
    def is_well_formed(self) -> bool:
        """Reviewer report must discuss missing evidence or untested branches for non-trivial approvals."""
        # An approval with empty missing_evidence AND empty untested_critical_branches
        # is rubber-stamping unless rationale is substantive
        if self.verdict == ReviewerVerdict.APPROVE:
            if (not self.missing_evidence and 
                not self.untested_critical_branches and
                len(self.rationale) < 50):
                return False
        return True
    
    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["verdict"] = self.verdict.value
        return d


def validate_reviewer_input(raw: dict[str, Any]) -> None:
    """Raise ValueError if reviewer input contains forbidden fields ANYWHERE in the tree."""
    _recursive_forbidden_scan(raw, path="root")


def _recursive_forbidden_scan(obj: Any, path: str) -> None:
    """Walk arbitrary nested dict/list structure, rejecting forbidden keys at any depth."""
    if isinstance(obj, dict):
        forbidden = set(obj.keys()) & FORBIDDEN_REVIEWER_INPUT_KEYS
        if forbidden:
            raise ValueError(
                f"Reviewer input contains forbidden builder-private fields at {path}: {sorted(forbidden)}"
            )
        for k, v in obj.items():
            _recursive_forbidden_scan(v, f"{path}.{k}")
    elif isinstance(obj, list):
        for i, item in enumerate(obj):
            _recursive_forbidden_scan(item, f"{path}[{i}]")

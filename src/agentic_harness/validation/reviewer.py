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


# Strict allowlist — only these top-level fields are permitted in reviewer input
ALLOWED_REVIEWER_INPUT_KEYS = {
    "spec",
    "criteria",
    "artifact_refs",
    "validation_verdict",
    "diffs",
}

# Strict allowlists for nested structures
ALLOWED_CRITERION_KEYS = {
    "criterion_id",
    "description",
    "criterion_class",
    "triple",
}
ALLOWED_TRIPLE_KEYS = {
    "build_target",
    "verification_command",
    "expected_output",
    "failure_signature",
}
ALLOWED_VERDICT_KEYS = {
    "task_id",
    "status",
    "must_pass_failures",
    "blocked_required",
    "reason",
    "criterion_results",
}

ALLOWED_ARTIFACT_REF_KEYS = {
    "artifact_id",
    "type",
    "path",
    "content_hash",
    "producer_run_id",
    "created_at",
    "immutable",
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
    """Strict allowlist validation of reviewer input.
    
    Only explicitly allowed keys are permitted. Unknown keys at ANY depth
    are rejected. This replaces denylist scanning with a strict contract.
    """
    _strict_allowlist_check(raw, ALLOWED_REVIEWER_INPUT_KEYS, path="root")
    # Deep structural checks
    if "criteria" in raw:
        for i, c in enumerate(raw["criteria"]):
            if isinstance(c, dict):
                _strict_allowlist_check(c, ALLOWED_CRITERION_KEYS, path=f"criteria[{i}]")
                if "triple" in c and isinstance(c["triple"], dict):
                    _strict_allowlist_check(
                        c["triple"], ALLOWED_TRIPLE_KEYS, path=f"criteria[{i}].triple"
                    )
    if "validation_verdict" in raw and isinstance(raw["validation_verdict"], dict):
        _strict_allowlist_check(
            raw["validation_verdict"], ALLOWED_VERDICT_KEYS, path="validation_verdict"
        )
    if "artifact_refs" in raw and isinstance(raw["artifact_refs"], list):
        for i, ar in enumerate(raw["artifact_refs"]):
            if isinstance(ar, dict):
                _strict_allowlist_check(
                    ar, ALLOWED_ARTIFACT_REF_KEYS, path=f"artifact_refs[{i}]"
                )
                # Type-check values: all scalar fields must be scalars,
                # not nested dicts/lists that could smuggle builder framing
                _SCALAR_ARTIFACT_FIELDS = {
                    "artifact_id": str,
                    "type": str,
                    "path": str,
                    "content_hash": str,
                    "producer_run_id": str,
                    "created_at": (int, float),
                    "immutable": bool,
                }
                for key, expected_type in _SCALAR_ARTIFACT_FIELDS.items():
                    if key in ar and not isinstance(ar[key], expected_type):
                        raise ValueError(
                            f"Reviewer input at artifact_refs[{i}].{key} must be "
                            f"{expected_type}, got {type(ar[key]).__name__}"
                        )
    # diffs must be a plain string — reject dict/list payloads
    if "diffs" in raw and not isinstance(raw["diffs"], str):
        raise ValueError(
            f"Reviewer input at diffs must be a string, got {type(raw['diffs']).__name__}"
        )


def _strict_allowlist_check(obj: dict[str, Any], allowed: set[str], path: str) -> None:
    """Reject any keys not in allowlist. Also reject known-forbidden keys explicitly."""
    if not isinstance(obj, dict):
        return
    extra = set(obj.keys()) - allowed
    if extra:
        raise ValueError(
            f"Reviewer input at {path} has disallowed keys: {sorted(extra)} "
            f"(allowed: {sorted(allowed)})"
        )
    # Belt-and-suspenders: reject forbidden names everywhere
    forbidden = set(obj.keys()) & FORBIDDEN_REVIEWER_INPUT_KEYS
    if forbidden:
        raise ValueError(
            f"Reviewer input contains forbidden builder-private fields at {path}: {sorted(forbidden)}"
        )

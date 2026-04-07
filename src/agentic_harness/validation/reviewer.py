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
    
    Rules:
    - Only explicitly allowed keys at any depth
    - Structural types enforced (criteria must be list-of-dict, verdict must be dict, etc.)
    - List items that aren't the expected type are rejected
    """
    _strict_allowlist_check(raw, ALLOWED_REVIEWER_INPUT_KEYS, path="root")
    
    # spec must be string
    if "spec" in raw and not isinstance(raw["spec"], str):
        raise ValueError(f"spec must be str, got {type(raw['spec']).__name__}")
    
    # criteria must be list-of-dict
    if "criteria" in raw:
        if not isinstance(raw["criteria"], list):
            raise ValueError("criteria must be a list")
        for i, c in enumerate(raw["criteria"]):
            if not isinstance(c, dict):
                raise ValueError(f"criteria[{i}] must be a dict, got {type(c).__name__}")
            _strict_allowlist_check(c, ALLOWED_CRITERION_KEYS, path=f"criteria[{i}]")
            # All scalar criterion fields must be strings
            for scalar_field in ("criterion_id", "description", "criterion_class"):
                if scalar_field in c and not isinstance(c[scalar_field], str):
                    raise ValueError(
                        f"criteria[{i}].{scalar_field} must be str, "
                        f"got {type(c[scalar_field]).__name__}"
                    )
            if "triple" in c:
                if not isinstance(c["triple"], dict):
                    raise ValueError(f"criteria[{i}].triple must be a dict")
                _strict_allowlist_check(
                    c["triple"], ALLOWED_TRIPLE_KEYS, path=f"criteria[{i}].triple"
                )
                # Triple fields must all be strings
                for tkey, tval in c["triple"].items():
                    if not isinstance(tval, str):
                        raise ValueError(
                            f"criteria[{i}].triple.{tkey} must be str, got {type(tval).__name__}"
                        )
    
    # validation_verdict must be a dict (NOT a list)
    if "validation_verdict" in raw:
        vv = raw["validation_verdict"]
        if not isinstance(vv, dict):
            raise ValueError(
                f"validation_verdict must be a dict, got {type(vv).__name__}"
            )
        _strict_allowlist_check(vv, ALLOWED_VERDICT_KEYS, path="validation_verdict")
        # Scalar verdict fields
        for s_field in ("task_id", "status", "reason"):
            if s_field in vv and not isinstance(vv[s_field], str):
                raise ValueError(
                    f"validation_verdict.{s_field} must be str, got {type(vv[s_field]).__name__}"
                )
        # List-of-string fields
        for list_field in ("must_pass_failures", "blocked_required"):
            if list_field in vv:
                if not isinstance(vv[list_field], list):
                    raise ValueError(
                        f"validation_verdict.{list_field} must be a list"
                    )
                for j, item in enumerate(vv[list_field]):
                    if not isinstance(item, str):
                        raise ValueError(
                            f"validation_verdict.{list_field}[{j}] must be str, "
                            f"got {type(item).__name__}"
                        )
        # criterion_results must be a list (of opaque dicts we don't deep-inspect,
        # but each must be a dict, not a smuggled string/list)
        if "criterion_results" in vv:
            if not isinstance(vv["criterion_results"], list):
                raise ValueError("validation_verdict.criterion_results must be a list")
            for j, cr in enumerate(vv["criterion_results"]):
                if not isinstance(cr, dict):
                    raise ValueError(
                        f"validation_verdict.criterion_results[{j}] must be a dict"
                    )
                # Recursive forbidden-key scan on criterion_result dicts
                _deep_forbidden_scan(cr, f"validation_verdict.criterion_results[{j}]")
    if "artifact_refs" in raw:
        if not isinstance(raw["artifact_refs"], list):
            raise ValueError("artifact_refs must be a list")
        for i, ar in enumerate(raw["artifact_refs"]):
            if not isinstance(ar, dict):
                raise ValueError(
                    f"artifact_refs[{i}] must be a dict, got {type(ar).__name__}"
                )
            _strict_allowlist_check(
                ar, ALLOWED_ARTIFACT_REF_KEYS, path=f"artifact_refs[{i}]"
            )
            if True:
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


def _deep_forbidden_scan(obj: Any, path: str) -> None:
    """Recursively reject any FORBIDDEN_REVIEWER_INPUT_KEYS at any depth."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k in FORBIDDEN_REVIEWER_INPUT_KEYS:
                raise ValueError(
                    f"Reviewer input contains forbidden builder-private field at {path}.{k}"
                )
            _deep_forbidden_scan(v, f"{path}.{k}")
    elif isinstance(obj, list):
        for i, item in enumerate(obj):
            _deep_forbidden_scan(item, f"{path}[{i}]")


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

"""Phase 3: Persistence for validation state, reviewer reports, ladder progress.

All durable state for Phase 3 lives here. Restart/recovery is a hard requirement:
evidence links, verdicts, reviewer reports, and ladder checkpoints must survive
process restart.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from typing import Any

from crucible.validation.artifact import ArtifactRef, ArtifactType
from crucible.validation.criterion import (
    Criterion, CriterionResult, CriterionVerdict, VerificationTriple, CriterionClass,
)
from crucible.validation.validator import ValidationVerdict, TaskCompletionStatus
from crucible.validation.ladder import LadderRung
from crucible.validation.reviewer import ReviewerReport, ReviewerVerdict


@dataclass
class ValidationStateRecord:
    """Durable validation state per task."""
    task_id: str
    criteria: list[Criterion]
    results: list[CriterionResult]
    verdict: ValidationVerdict | None = None
    current_rung: LadderRung = LadderRung.NONE
    reviewer_reports: list[ReviewerReport] = field(default_factory=list)
    
    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "criteria": [c.to_dict() for c in self.criteria],
            "results": [_result_to_dict(r) for r in self.results],
            "verdict": _verdict_to_dict(self.verdict) if self.verdict else None,
            "current_rung": int(self.current_rung),
            "reviewer_reports": [r.to_dict() for r in self.reviewer_reports],
        }
    
    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ValidationStateRecord":
        return cls(
            task_id=data["task_id"],
            criteria=[Criterion.from_dict(c) for c in data["criteria"]],
            results=[_result_from_dict(r) for r in data["results"]],
            verdict=_verdict_from_dict(data["verdict"]) if data.get("verdict") else None,
            current_rung=LadderRung(data.get("current_rung", 0)),
            reviewer_reports=[_reviewer_report_from_dict(r) for r in data.get("reviewer_reports", [])],
        )
    
    def save(self, path: str) -> None:
        with open(path, "w") as f:
            json.dump(self.to_dict(), f, indent=2)
    
    @classmethod
    def load(cls, path: str) -> "ValidationStateRecord":
        with open(path, "r") as f:
            return cls.from_dict(json.load(f))


def _result_to_dict(r: CriterionResult) -> dict[str, Any]:
    return {
        "criterion_id": r.criterion_id,
        "verdict": r.verdict.value,
        "evidence_artifacts": [a.to_dict() for a in r.evidence_artifacts],
        "actual_output": r.actual_output,
        "error": r.error,
        "executed_command": r.executed_command,
        "run_id": r.run_id,
    }


def _result_from_dict(d: dict[str, Any]) -> CriterionResult:
    return CriterionResult(
        criterion_id=d["criterion_id"],
        verdict=CriterionVerdict(d["verdict"]),
        evidence_artifacts=[ArtifactRef.from_dict(a) for a in d.get("evidence_artifacts", [])],
        actual_output=d.get("actual_output", ""),
        error=d.get("error", ""),
        executed_command=d.get("executed_command", ""),
        run_id=d.get("run_id", ""),
    )


def _verdict_to_dict(v: ValidationVerdict) -> dict[str, Any]:
    return {
        "task_id": v.task_id,
        "status": v.status.value,
        "criterion_results": [_result_to_dict(r) for r in v.criterion_results],
        "must_pass_failures": list(v.must_pass_failures),
        "blocked_required": list(v.blocked_required),
        "reason": v.reason,
    }


def _verdict_from_dict(d: dict[str, Any]) -> ValidationVerdict:
    return ValidationVerdict(
        task_id=d["task_id"],
        status=TaskCompletionStatus(d["status"]),
        criterion_results=[_result_from_dict(r) for r in d["criterion_results"]],
        must_pass_failures=list(d.get("must_pass_failures", [])),
        blocked_required=list(d.get("blocked_required", [])),
        reason=d.get("reason", ""),
    )


def _reviewer_report_from_dict(d: dict[str, Any]) -> ReviewerReport:
    return ReviewerReport(
        task_id=d["task_id"],
        reviewer_run_id=d["reviewer_run_id"],
        covered_criteria=list(d["covered_criteria"]),
        missing_evidence=list(d["missing_evidence"]),
        untested_critical_branches=list(d["untested_critical_branches"]),
        escaped_defect_risk=d["escaped_defect_risk"],
        verdict=ReviewerVerdict(d["verdict"]),
        rationale=d["rationale"],
    )

"""Phase 3: Validator — gate-based verdict computation.

Rules (fail-closed):
1. A criterion can only PASS if it has at least one reachable artifact ref
2. A must-pass criterion that FAILS or is BLOCKED => task not complete
3. Empty criteria set OR empty must-pass set => fail closed (not complete)
4. Pass-rate heuristics are NEVER used
5. Blocked required evidence blocks completion
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from agentic_harness.validation.criterion import (
    Criterion, CriterionClass, CriterionResult, CriterionVerdict,
)


class TaskCompletionStatus(str, Enum):
    COMPLETE = "complete"
    INCOMPLETE = "incomplete"
    FAILED = "failed"


@dataclass
class ValidationVerdict:
    """Result of validating a task against its criteria."""
    task_id: str
    status: TaskCompletionStatus
    criterion_results: list[CriterionResult]
    must_pass_failures: list[str] = field(default_factory=list)
    blocked_required: list[str] = field(default_factory=list)
    reason: str = ""
    
    @property
    def is_complete(self) -> bool:
        return self.status == TaskCompletionStatus.COMPLETE


class Validator:
    """Computes validation verdicts using gate semantics.
    
    Never uses pass-rate heuristics. Every must-pass criterion must:
    - PASS with reachable evidence artifacts, OR
    - Be explicitly waived (not supported in Phase 3)
    """
    
    def validate(
        self,
        task_id: str,
        criteria: list[Criterion],
        results: list[CriterionResult],
    ) -> ValidationVerdict:
        """Compute validation verdict.
        
        Fail-closed rules:
        - Empty criteria => FAILED
        - No must-pass criteria => FAILED
        - Any must-pass FAIL or BLOCKED => INCOMPLETE
        - Any criterion PASS without real evidence => FAIL (downgrade)
        """
        # Rule: empty criteria fails closed
        if not criteria:
            return ValidationVerdict(
                task_id=task_id,
                status=TaskCompletionStatus.FAILED,
                criterion_results=results,
                reason="No criteria defined (fail closed)",
            )
        
        # Rule: must have at least one must-pass
        must_pass_criteria = [c for c in criteria if c.criterion_class == CriterionClass.MUST_PASS]
        if not must_pass_criteria:
            return ValidationVerdict(
                task_id=task_id,
                status=TaskCompletionStatus.FAILED,
                criterion_results=results,
                reason="No must-pass criteria defined (fail closed)",
            )
        
        # Build criterion lookup
        criteria_by_id = {c.criterion_id: c for c in criteria}
        
        # Reject orphan results (results for criteria not in set)
        for r in results:
            if r.criterion_id not in criteria_by_id:
                raise ValueError(
                    f"Orphan result: criterion {r.criterion_id} not in criteria set"
                )
        
        # Downgrade vacuous PASSes to FAIL — enforce command provenance
        normalized_results: list[CriterionResult] = []
        for r in results:
            if r.verdict == CriterionVerdict.PASS:
                crit = criteria_by_id[r.criterion_id]
                # Evidence must come from this criterion's verification command
                if not r.has_real_evidence(expected_command=crit.triple.verification_command):
                    normalized_results.append(CriterionResult(
                        criterion_id=r.criterion_id,
                        verdict=CriterionVerdict.FAIL,
                        evidence_artifacts=r.evidence_artifacts,
                        actual_output=r.actual_output,
                        error="PASS downgraded: evidence provenance failed (missing/wrong-run/wrong-command artifacts)",
                        executed_command=r.executed_command,
                        run_id=r.run_id,
                    ))
                else:
                    normalized_results.append(r)
            else:
                normalized_results.append(r)
        
        # Check each must-pass criterion
        must_pass_ids = {c.criterion_id for c in must_pass_criteria}
        results_by_criterion = {r.criterion_id: r for r in normalized_results}
        
        must_pass_failures: list[str] = []
        blocked_required: list[str] = []
        
        for mp_id in must_pass_ids:
            r = results_by_criterion.get(mp_id)
            if r is None:
                # No result at all = blocked
                blocked_required.append(mp_id)
                continue
            if r.verdict == CriterionVerdict.BLOCKED:
                blocked_required.append(mp_id)
            elif r.verdict in {CriterionVerdict.FAIL, CriterionVerdict.PENDING}:
                must_pass_failures.append(mp_id)
        
        if must_pass_failures or blocked_required:
            reason_parts = []
            if must_pass_failures:
                reason_parts.append(f"must-pass failures: {must_pass_failures}")
            if blocked_required:
                reason_parts.append(f"blocked required: {blocked_required}")
            return ValidationVerdict(
                task_id=task_id,
                status=TaskCompletionStatus.INCOMPLETE,
                criterion_results=normalized_results,
                must_pass_failures=must_pass_failures,
                blocked_required=blocked_required,
                reason="; ".join(reason_parts),
            )
        
        # All must-pass criteria passed with real evidence
        return ValidationVerdict(
            task_id=task_id,
            status=TaskCompletionStatus.COMPLETE,
            criterion_results=normalized_results,
            reason="All must-pass criteria PASS with verified artifacts",
        )

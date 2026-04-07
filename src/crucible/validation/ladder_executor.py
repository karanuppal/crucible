"""Phase 3: Validation ladder executor.

Runs criteria through the validation ladder rung by rung:
  STATIC → UNIT → INTEGRATION → END_TO_END

Semantics:
- A rung fails if ANY of its criteria fail
- A rung failure blocks all later rungs (fail-fast)
- Per-rung transcripts are persisted
- Execution can resume from a persisted partial state
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field, asdict
from typing import Any, Callable

from crucible.validation.criterion import (
    Criterion, CriterionResult, CriterionVerdict,
)
from crucible.validation.ladder import LadderRung, next_rung
from crucible.validation.validator import Validator, ValidationVerdict, TaskCompletionStatus


@dataclass
class RungResult:
    """Outcome of executing a single rung."""
    rung: LadderRung
    criterion_results: list[CriterionResult]
    passed: bool
    transcript: str = ""


@dataclass
class LadderExecutionState:
    """Persistable ladder execution state."""
    task_id: str
    completed_rungs: list[LadderRung] = field(default_factory=list)
    rung_results: list[RungResult] = field(default_factory=list)
    last_failure_rung: LadderRung | None = None
    is_complete: bool = False


class LadderExecutor:
    """Executes validation ladder rung-by-rung with fail-fast semantics.
    
    rung_runner: callable(rung, criteria) -> (list[CriterionResult], transcript)
    """
    
    def __init__(
        self,
        validator: Validator,
        rung_runner: Callable[[LadderRung, list[Criterion]], tuple[list[CriterionResult], str]],
    ) -> None:
        self._validator = validator
        self._rung_runner = rung_runner
    
    def execute(
        self,
        task_id: str,
        criteria_by_rung: dict[LadderRung, list[Criterion]],
        start_from: LadderRung = LadderRung.STATIC,
        state: LadderExecutionState | None = None,
    ) -> LadderExecutionState:
        """Execute ladder from start_from to END_TO_END.
        
        Fail-fast: if any rung fails, stop and do not run later rungs.
        """
        if state is None:
            state = LadderExecutionState(task_id=task_id)
        
        current = start_from
        while current is not None:
            criteria = criteria_by_rung.get(current, [])
            
            if not criteria:
                # No criteria at this rung — skip and advance
                state.completed_rungs.append(current)
                nxt = next_rung(current)
                current = nxt
                continue
            
            # Execute rung
            results, transcript = self._rung_runner(current, criteria)
            
            # Validate against criteria at this rung
            verdict = self._validator.validate(task_id, criteria, results)
            rung_passed = verdict.status == TaskCompletionStatus.COMPLETE
            
            state.rung_results.append(RungResult(
                rung=current,
                criterion_results=results,
                passed=rung_passed,
                transcript=transcript,
            ))
            state.completed_rungs.append(current)
            
            if not rung_passed:
                # Fail-fast: mark failure and stop
                state.last_failure_rung = current
                state.is_complete = False
                return state
            
            nxt = next_rung(current)
            current = nxt
        
        state.is_complete = True
        return state
    
    def resume(
        self,
        task_id: str,
        criteria_by_rung: dict[LadderRung, list[Criterion]],
        state: LadderExecutionState,
    ) -> LadderExecutionState:
        """Resume execution from the rung after the last completed one."""
        if state.is_complete:
            return state
        
        # Find resume point
        if state.last_failure_rung is not None:
            # Failed rung must be re-executed
            resume_from = state.last_failure_rung
            # Clear failure marker and re-execute from here
            state.last_failure_rung = None
            # Remove the last rung result (so we can re-run it)
            if state.rung_results and state.rung_results[-1].rung == resume_from:
                state.rung_results.pop()
            if resume_from in state.completed_rungs:
                state.completed_rungs.remove(resume_from)
        elif state.completed_rungs:
            last_done = state.completed_rungs[-1]
            nxt = next_rung(last_done)
            if nxt is None:
                state.is_complete = True
                return state
            resume_from = nxt
        else:
            resume_from = LadderRung.STATIC
        
        return self.execute(task_id, criteria_by_rung, start_from=resume_from, state=state)


def save_ladder_state(state: LadderExecutionState, path: str) -> None:
    """Atomic save of ladder state."""
    data = {
        "task_id": state.task_id,
        "completed_rungs": [int(r) for r in state.completed_rungs],
        "rung_results": [
            {
                "rung": int(rr.rung),
                "passed": rr.passed,
                "transcript": rr.transcript,
                # Criterion results persisted as IDs + verdicts only for brevity here
                "criterion_results": [
                    {"criterion_id": r.criterion_id, "verdict": r.verdict.value}
                    for r in rr.criterion_results
                ],
            }
            for rr in state.rung_results
        ],
        "last_failure_rung": int(state.last_failure_rung) if state.last_failure_rung is not None else None,
        "is_complete": state.is_complete,
    }
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(data, f, indent=2)
    os.replace(tmp, path)


def load_ladder_state(path: str) -> LadderExecutionState:
    with open(path, "r") as f:
        data = json.load(f)
    state = LadderExecutionState(
        task_id=data["task_id"],
        completed_rungs=[LadderRung(r) for r in data["completed_rungs"]],
        last_failure_rung=LadderRung(data["last_failure_rung"]) if data.get("last_failure_rung") is not None else None,
        is_complete=data.get("is_complete", False),
    )
    for rr_data in data.get("rung_results", []):
        state.rung_results.append(RungResult(
            rung=LadderRung(rr_data["rung"]),
            criterion_results=[
                CriterionResult(
                    criterion_id=r["criterion_id"],
                    verdict=CriterionVerdict(r["verdict"]),
                )
                for r in rr_data.get("criterion_results", [])
            ],
            passed=rr_data["passed"],
            transcript=rr_data.get("transcript", ""),
        ))
    return state

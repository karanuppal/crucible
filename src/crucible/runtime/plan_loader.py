"""Phase 8: Convert a normalized plan dict into TaskDefinition objects."""

from __future__ import annotations

from typing import Any

from crucible.orchestrator.orchestrator import TaskDefinition
from crucible.runner.run_graph import RunRole
from crucible.validation.criterion import (
    Criterion, CriterionClass, VerificationTriple,
)


_ROLE_MAP = {
    "builder": RunRole.BUILDER,
    "reviewer": RunRole.REVIEWER,
    "debugger": RunRole.DEBUGGER,
    "researcher": RunRole.RESEARCHER,
    "integrator": RunRole.INTEGRATOR,
    "salvage": RunRole.SALVAGE,
}


def plan_to_task_definitions(plan: dict[str, Any]) -> list[TaskDefinition]:
    """Convert a preflight-validated plan into a list of TaskDefinition.
    
    The input plan must already have passed `lint_plan()`.
    """
    tasks_out: list[TaskDefinition] = []
    for task in plan.get("tasks", []):
        criteria_out: list[Criterion] = []
        for crit in task.get("criteria", []):
            triple = crit.get("triple", {})
            criteria_out.append(Criterion(
                criterion_id=crit["criterion_id"],
                description=task.get("description", ""),
                criterion_class=CriterionClass(crit.get("criterion_class", "must_pass")),
                triple=VerificationTriple(
                    build_target=triple.get("build_target", ""),
                    verification_command=triple.get("verification_command", ""),
                    expected_output=triple.get("expected_output", ""),
                    failure_signature=triple.get("failure_signature", ""),
                ),
            ))
        
        role_str = task.get("role", "builder")
        role = _ROLE_MAP.get(role_str, RunRole.BUILDER)
        
        tasks_out.append(TaskDefinition(
            task_id=task["task_id"],
            description=task["description"],
            criteria=criteria_out,
            role=role,
            intensity_hint=task.get("intensity_hint", "M"),
            spec_command=task.get("spec_command", ""),
        ))
    
    return tasks_out

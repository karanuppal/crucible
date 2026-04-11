from __future__ import annotations

from dataclasses import dataclass
from typing import Any


class PlanningError(ValueError):
    pass


@dataclass
class AmbiguityReport:
    should_escalate: bool
    reasons: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "should_escalate": self.should_escalate,
            "reasons": list(self.reasons),
        }


QUESTION_TOKENS = ("tbd", "todo", "???", "unclear", "decide later")


def detect_ambiguity(submitted_plan: dict[str, Any]) -> AmbiguityReport:
    reasons: list[str] = []
    spec = str(submitted_plan.get("spec") or "")
    if not spec.strip():
        reasons.append("spec is empty")
    lowered = spec.lower()
    for token in QUESTION_TOKENS:
        if token in lowered:
            reasons.append(f"spec contains ambiguity marker '{token}'")
    for task in submitted_plan.get("tasks", []) or []:
        description = str(task.get("description") or "")
        lowered_description = description.lower()
        for token in QUESTION_TOKENS:
            if token in lowered_description:
                reasons.append(
                    f"task {task.get('task_id', '<unknown>')} contains ambiguity marker '{token}'"
                )
                break
    return AmbiguityReport(should_escalate=bool(reasons), reasons=reasons)



def build_plan_artifact(
    *,
    run_id: str,
    submitted_plan: dict[str, Any],
    embedding_surface: str = "",
    embedding_session_ref: str = "",
) -> dict[str, Any]:
    tasks_out: list[dict[str, Any]] = []
    for task in submitted_plan.get("tasks", []):
        dependencies = task.get("dependencies")
        if not isinstance(dependencies, list):
            dependencies = []
        criteria = task.get("criteria", []) if isinstance(task.get("criteria"), list) else []
        acceptance_criteria = [
            str(criterion.get("criterion_id") or "")
            for criterion in criteria
            if str(criterion.get("criterion_id") or "")
        ]
        if not acceptance_criteria and task.get("description"):
            acceptance_criteria = [str(task["description"])]

        must_pass = []
        informational = []
        required_commands = []
        for criterion in criteria:
            criterion_id = str(criterion.get("criterion_id") or "")
            triple = criterion.get("triple") if isinstance(criterion.get("triple"), dict) else {}
            command = str(triple.get("verification_command") or "").strip()
            if command:
                required_commands.append(command)
            if criterion.get("criterion_class", "must_pass") == "must_pass":
                if criterion_id:
                    must_pass.append(criterion_id)
            elif criterion_id:
                informational.append(criterion_id)

        review_required = task.get("role", "builder") != "researcher"
        tasks_out.append({
            "task_id": task["task_id"],
            "description": task.get("description", ""),
            "task_type": str(task.get("role") or "builder"),
            "dependencies": [str(dep) for dep in dependencies],
            "acceptance_criteria": acceptance_criteria,
            "validation_policy": {
                "required_commands": required_commands,
                "must_pass": must_pass,
                "informational": informational,
            },
            "review_policy": {
                "required": review_required,
                "tier": "standard",
            },
        })

    plan_artifact = {
        "plan_id": f"plan-{run_id}",
        "run_id": run_id,
        "project_id": submitted_plan.get("project_id", ""),
        "build_id": submitted_plan.get("build_id", ""),
        "goal": submitted_plan.get("spec", ""),
        "source": {
            "submitted_by": embedding_surface or "cli",
            "embedding_surface": embedding_surface,
            "embedding_session_ref": embedding_session_ref,
        },
        "status": "validated",
        "planning_version": "p1",
        "tasks": tasks_out,
        "global_policy": {
            "max_attempts_per_task": 4,
            "allow_human_clarification": True,
        },
        "artifacts": {
            "repo_summary_ref": None,
            "ambiguity_report_ref": None,
        },
    }
    validate_plan_artifact(plan_artifact)
    return plan_artifact



def validate_plan_artifact(plan: dict[str, Any]) -> None:
    required_top = [
        "plan_id",
        "run_id",
        "project_id",
        "build_id",
        "goal",
        "source",
        "status",
        "planning_version",
        "tasks",
        "global_policy",
        "artifacts",
    ]
    for field in required_top:
        if field not in plan:
            raise PlanningError(f"plan missing required field '{field}'")
    if plan.get("status") != "validated":
        raise PlanningError("plan status must be 'validated'")
    tasks = plan.get("tasks")
    if not isinstance(tasks, list) or not tasks:
        raise PlanningError("plan must contain at least one task")
    seen_task_ids: set[str] = set()
    for task in tasks:
        task_id = str(task.get("task_id") or "")
        if not task_id:
            raise PlanningError("plan task missing task_id")
        if task_id in seen_task_ids:
            raise PlanningError(f"duplicate task_id in plan: {task_id}")
        seen_task_ids.add(task_id)
        for field in ("dependencies", "acceptance_criteria", "validation_policy", "review_policy"):
            if field not in task:
                raise PlanningError(f"plan task {task_id} missing '{field}'")
        if not isinstance(task["dependencies"], list):
            raise PlanningError(f"plan task {task_id} dependencies must be a list")
        if not isinstance(task["acceptance_criteria"], list) or not task["acceptance_criteria"]:
            raise PlanningError(f"plan task {task_id} acceptance_criteria must be a non-empty list")
        validation_policy = task["validation_policy"]
        if not isinstance(validation_policy, dict):
            raise PlanningError(f"plan task {task_id} validation_policy must be a dict")
        for policy_field in ("required_commands", "must_pass", "informational"):
            if policy_field not in validation_policy or not isinstance(validation_policy[policy_field], list):
                raise PlanningError(
                    f"plan task {task_id} validation_policy.{policy_field} must be a list"
                )
        review_policy = task["review_policy"]
        if not isinstance(review_policy, dict):
            raise PlanningError(f"plan task {task_id} review_policy must be a dict")
        if not isinstance(review_policy.get("required"), bool):
            raise PlanningError(f"plan task {task_id} review_policy.required must be a bool")
        if not isinstance(review_policy.get("tier"), str) or not review_policy.get("tier"):
            raise PlanningError(f"plan task {task_id} review_policy.tier must be a non-empty string")
        for dep in task["dependencies"]:
            if dep not in seen_task_ids and dep not in {t.get('task_id') for t in tasks}:
                raise PlanningError(f"plan task {task_id} depends on unknown task '{dep}'")



def ensure_validated_plan(plan: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(plan, dict):
        raise PlanningError("validated plan.json is missing")
    validate_plan_artifact(plan)
    return plan

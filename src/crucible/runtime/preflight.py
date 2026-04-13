"""Phase 8 §27: TaskDefinition preflight validator.

Rejects structurally invalid OR operationally vague task plans BEFORE
the orchestrator runs. Catches problems at intake, not at validation time.

Schema in v5.3 §27.4.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Any


class LintSeverity(str, Enum):
    ERROR = "error"      # blocks the run
    WARNING = "warning"  # surfaced but doesn't block
    INFO = "info"


@dataclass
class LintFinding:
    severity: LintSeverity
    code: str
    message: str
    task_id: str = ""
    criterion_id: str = ""

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["severity"] = self.severity.value
        return d


@dataclass
class LintResult:
    valid: bool
    findings: list[LintFinding] = field(default_factory=list)
    normalized_plan: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "valid": self.valid,
            "findings": [f.to_dict() for f in self.findings],
            "normalized_plan": self.normalized_plan,
        }
    
    def errors(self) -> list[LintFinding]:
        return [f for f in self.findings if f.severity == LintSeverity.ERROR]
    
    def warnings(self) -> list[LintFinding]:
        return [f for f in self.findings if f.severity == LintSeverity.WARNING]


# ─────────────────────────────────────────────────────────────────
# Heuristics
# ─────────────────────────────────────────────────────────────────

VAGUE_DESCRIPTION_TOKENS = {
    "works", "properly", "correctly", "as expected", "well",
    "good", "fine", "ok", "okay", "succeeds",
}

GENERIC_BUILD_TARGETS = {
    "project", "code", "the project", "the code", "everything", "all",
}

GENERIC_EXPECTED_OUTPUTS = {
    "success", "done", "passes", "pass", "ok", "okay", "complete", "finished",
}

VALID_ROLES = {"builder", "reviewer", "debugger", "researcher", "integrator", "salvage", "bugfix"}
VALID_INTENSITIES = {"S", "M", "L"}
VALID_CRITERION_CLASSES = {"must_pass", "informational"}

MIN_DESCRIPTION_LENGTH = 10
MIN_EXPECTED_OUTPUT_LENGTH = 4


def lint_plan(plan: dict[str, Any]) -> LintResult:
    """Lint a Crucible task plan. Returns valid=False on any ERROR finding."""
    findings: list[LintFinding] = []
    
    # ─── Top-level structural ───
    
    if not isinstance(plan, dict):
        findings.append(LintFinding(
            severity=LintSeverity.ERROR,
            code="PLAN_NOT_DICT",
            message=f"plan must be a JSON object, got {type(plan).__name__}",
        ))
        return LintResult(valid=False, findings=findings)
    
    for required in ("spec", "project_id", "build_id", "tasks"):
        if required not in plan:
            findings.append(LintFinding(
                severity=LintSeverity.ERROR,
                code="MISSING_TOP_LEVEL_FIELD",
                message=f"plan missing required field '{required}'",
            ))
    
    if "spec" in plan and not isinstance(plan["spec"], str):
        findings.append(LintFinding(
            severity=LintSeverity.ERROR,
            code="SPEC_NOT_STRING",
            message="spec must be a string",
        ))
    if "project_id" in plan and not isinstance(plan.get("project_id"), str):
        findings.append(LintFinding(
            severity=LintSeverity.ERROR,
            code="PROJECT_ID_NOT_STRING",
            message="project_id must be a string",
        ))
    if "build_id" in plan and not isinstance(plan.get("build_id"), str):
        findings.append(LintFinding(
            severity=LintSeverity.ERROR,
            code="BUILD_ID_NOT_STRING",
            message="build_id must be a string",
        ))
    
    tasks = plan.get("tasks")
    if not isinstance(tasks, list):
        findings.append(LintFinding(
            severity=LintSeverity.ERROR,
            code="TASKS_NOT_LIST",
            message="tasks must be a list",
        ))
        return LintResult(valid=False, findings=findings)
    
    if len(tasks) == 0:
        findings.append(LintFinding(
            severity=LintSeverity.ERROR,
            code="ZERO_TASKS",
            message="plan has no tasks",
        ))
        return LintResult(valid=False, findings=findings)
    
    # ─── Per-task validation ───
    
    seen_task_ids: set[str] = set()
    seen_criterion_ids: set[str] = set()
    seen_triple_keys: dict[tuple[str, str], list[str]] = {}  # (cmd, expected) → [task_ids]
    
    normalized_tasks: list[dict[str, Any]] = []
    
    for i, task in enumerate(tasks):
        if not isinstance(task, dict):
            findings.append(LintFinding(
                severity=LintSeverity.ERROR,
                code="TASK_NOT_DICT",
                message=f"tasks[{i}] must be a dict, got {type(task).__name__}",
            ))
            continue
        
        task_id = task.get("task_id", "")
        if not isinstance(task_id, str) or not task_id.strip():
            findings.append(LintFinding(
                severity=LintSeverity.ERROR,
                code="TASK_ID_EMPTY",
                message=f"tasks[{i}].task_id is empty or not a string",
            ))
            continue
        
        if task_id in seen_task_ids:
            findings.append(LintFinding(
                severity=LintSeverity.ERROR,
                code="TASK_ID_DUPLICATE",
                message=f"duplicate task_id '{task_id}'",
                task_id=task_id,
            ))
        seen_task_ids.add(task_id)
        
        # Description
        description = task.get("description", "")
        if not isinstance(description, str) or len(description.strip()) == 0:
            findings.append(LintFinding(
                severity=LintSeverity.ERROR,
                code="DESCRIPTION_EMPTY",
                message=f"task {task_id} has empty description",
                task_id=task_id,
            ))
        elif len(description.strip()) < MIN_DESCRIPTION_LENGTH:
            findings.append(LintFinding(
                severity=LintSeverity.ERROR,
                code="DESCRIPTION_TOO_SHORT",
                message=f"task {task_id} description must be ≥{MIN_DESCRIPTION_LENGTH} chars",
                task_id=task_id,
            ))
        else:
            # Vague language check
            lower = description.lower()
            for token in VAGUE_DESCRIPTION_TOKENS:
                if re.search(rf"\b{re.escape(token)}\b", lower):
                    # Vague AND no measurable condition (numbers, specific files, function names, etc.)
                    has_measurable = bool(re.search(r"[\d/]|test_|def |\.py|\.js|\.ts|src/|tests/", description))
                    if not has_measurable:
                        findings.append(LintFinding(
                            severity=LintSeverity.ERROR,
                            code="VAGUE_DESCRIPTION",
                            message=f"task {task_id} description uses weak token '{token}' without measurable condition",
                            task_id=task_id,
                        ))
                        break
        
        # Role / intensity
        role = task.get("role", "builder")
        if role not in VALID_ROLES:
            findings.append(LintFinding(
                severity=LintSeverity.ERROR,
                code="INVALID_ROLE",
                message=f"task {task_id} has invalid role '{role}'",
                task_id=task_id,
            ))
        
        intensity = task.get("intensity_hint", "M")
        if intensity not in VALID_INTENSITIES:
            findings.append(LintFinding(
                severity=LintSeverity.WARNING,
                code="INVALID_INTENSITY",
                message=f"task {task_id} has invalid intensity_hint '{intensity}', defaulting to M",
                task_id=task_id,
            ))
            intensity = "M"
        
        # Criteria
        criteria = task.get("criteria", [])
        if not isinstance(criteria, list) or len(criteria) == 0:
            findings.append(LintFinding(
                severity=LintSeverity.ERROR,
                code="ZERO_CRITERIA",
                message=f"task {task_id} has no criteria",
                task_id=task_id,
            ))
            continue
        
        must_pass_count = 0
        normalized_criteria: list[dict[str, Any]] = []
        
        for j, criterion in enumerate(criteria):
            if not isinstance(criterion, dict):
                findings.append(LintFinding(
                    severity=LintSeverity.ERROR,
                    code="CRITERION_NOT_DICT",
                    message=f"task {task_id} criteria[{j}] is not a dict",
                    task_id=task_id,
                ))
                continue
            
            criterion_id = criterion.get("criterion_id", "")
            if not isinstance(criterion_id, str) or not criterion_id.strip():
                findings.append(LintFinding(
                    severity=LintSeverity.ERROR,
                    code="CRITERION_ID_EMPTY",
                    message=f"task {task_id} criteria[{j}] missing criterion_id",
                    task_id=task_id,
                ))
                continue
            
            global_cid = f"{task_id}.{criterion_id}"
            if global_cid in seen_criterion_ids:
                findings.append(LintFinding(
                    severity=LintSeverity.ERROR,
                    code="CRITERION_ID_DUPLICATE",
                    message=f"duplicate criterion_id within task {task_id}: {criterion_id}",
                    task_id=task_id,
                    criterion_id=criterion_id,
                ))
            seen_criterion_ids.add(global_cid)
            
            criterion_class = criterion.get("criterion_class", "must_pass")
            if criterion_class not in VALID_CRITERION_CLASSES:
                findings.append(LintFinding(
                    severity=LintSeverity.ERROR,
                    code="INVALID_CRITERION_CLASS",
                    message=f"task {task_id} criterion {criterion_id} has invalid class '{criterion_class}'",
                    task_id=task_id,
                    criterion_id=criterion_id,
                ))
            if criterion_class == "must_pass":
                must_pass_count += 1
            
            # Triple
            triple = criterion.get("triple", {})
            if not isinstance(triple, dict):
                findings.append(LintFinding(
                    severity=LintSeverity.ERROR,
                    code="TRIPLE_NOT_DICT",
                    message=f"task {task_id} criterion {criterion_id} triple is not a dict",
                    task_id=task_id,
                    criterion_id=criterion_id,
                ))
                continue
            
            for tk in ("build_target", "verification_command", "expected_output"):
                v = triple.get(tk, "")
                if not isinstance(v, str) or not v.strip():
                    findings.append(LintFinding(
                        severity=LintSeverity.ERROR,
                        code="TRIPLE_FIELD_MISSING",
                        message=f"task {task_id} criterion {criterion_id} triple.{tk} is empty",
                        task_id=task_id,
                        criterion_id=criterion_id,
                    ))
            
            build_target = triple.get("build_target", "").strip().lower()
            if build_target in GENERIC_BUILD_TARGETS:
                findings.append(LintFinding(
                    severity=LintSeverity.ERROR,
                    code="GENERIC_BUILD_TARGET",
                    message=f"task {task_id} criterion {criterion_id} build_target '{build_target}' is too generic",
                    task_id=task_id,
                    criterion_id=criterion_id,
                ))
            
            expected = triple.get("expected_output", "")
            if expected and len(expected.strip()) < MIN_EXPECTED_OUTPUT_LENGTH:
                findings.append(LintFinding(
                    severity=LintSeverity.ERROR,
                    code="EXPECTED_OUTPUT_TOO_SHORT",
                    message=f"task {task_id} criterion {criterion_id} expected_output must be ≥{MIN_EXPECTED_OUTPUT_LENGTH} chars",
                    task_id=task_id,
                    criterion_id=criterion_id,
                ))
            elif expected.strip().lower() in GENERIC_EXPECTED_OUTPUTS:
                findings.append(LintFinding(
                    severity=LintSeverity.ERROR,
                    code="GENERIC_EXPECTED_OUTPUT",
                    message=f"task {task_id} criterion {criterion_id} expected_output '{expected}' is too generic",
                    task_id=task_id,
                    criterion_id=criterion_id,
                ))
            
            # Track triple uniqueness
            cmd = triple.get("verification_command", "").strip()
            exp = expected.strip()
            if cmd and exp:
                key = (cmd, exp)
                seen_triple_keys.setdefault(key, []).append(f"{task_id}.{criterion_id}")
            
            # Normalize whitespace
            normalized_criterion = {
                "criterion_id": criterion_id.strip(),
                "criterion_class": criterion_class,
                "triple": {
                    "build_target": triple.get("build_target", "").strip(),
                    "verification_command": triple.get("verification_command", "").strip(),
                    "expected_output": expected.strip(),
                    "failure_signature": triple.get("failure_signature", "").strip(),
                },
            }
            normalized_criteria.append(normalized_criterion)
        
        if must_pass_count == 0:
            findings.append(LintFinding(
                severity=LintSeverity.ERROR,
                code="NO_MUST_PASS_CRITERIA",
                message=f"task {task_id} has no must_pass criteria",
                task_id=task_id,
            ))
        
        raw_dependencies = task.get("dependencies", [])
        if raw_dependencies is None:
            raw_dependencies = []
        if not isinstance(raw_dependencies, list):
            findings.append(LintFinding(
                severity=LintSeverity.ERROR,
                code="DEPENDENCIES_NOT_LIST",
                message=f"task {task_id} dependencies must be a list",
                task_id=task_id,
            ))
            raw_dependencies = []
        dependencies = [str(dep).strip() for dep in raw_dependencies if str(dep).strip()]
        for dep in dependencies:
            if dep == task_id:
                findings.append(LintFinding(
                    severity=LintSeverity.ERROR,
                    code="SELF_DEPENDENCY",
                    message=f"task {task_id} cannot depend on itself",
                    task_id=task_id,
                ))

        review_policy = task.get("review_policy") if isinstance(task.get("review_policy"), dict) else {}
        if isinstance(task.get("review_required"), bool):
            review_required = task.get("review_required")
        elif isinstance(review_policy.get("required"), bool):
            review_required = review_policy.get("required")
        else:
            review_required = role != "researcher"
        review_tier = review_policy.get("tier") if isinstance(review_policy.get("tier"), str) and review_policy.get("tier", "").strip() else ("standard" if review_required else "none")

        normalized_task = {
            "task_id": task_id.strip(),
            "description": description.strip(),
            "dependencies": dependencies,
            "criteria": normalized_criteria,
            "role": role,
            "task_type": task.get("task_type", role).strip() if isinstance(task.get("task_type"), str) else role,
            "bugfix": task.get("bugfix", {}) if isinstance(task.get("bugfix"), dict) else {},
            "intensity_hint": intensity,
            "spec_command": task.get("spec_command", "").strip() if isinstance(task.get("spec_command"), str) else "",
            "retryable": task.get("retryable", True) if isinstance(task.get("retryable"), bool) else True,
        }
        if isinstance(task.get("review_required"), bool):
            normalized_task["review_required"] = review_required
        if isinstance(task.get("review_policy"), dict):
            normalized_task["review_policy"] = {"required": review_required, "tier": review_tier.strip().lower()}
        normalized_tasks.append(normalized_task)
    
    # Cross-task duplicate triple check
    for key, cids in seen_triple_keys.items():
        if len(cids) > 1:
            findings.append(LintFinding(
                severity=LintSeverity.ERROR,
                code="DUPLICATE_TRIPLE_ACROSS_CRITERIA",
                message=f"identical (verification_command, expected_output) used by multiple criteria: {cids}",
            ))

    task_id_set = {task["task_id"] for task in normalized_tasks}
    for task in normalized_tasks:
        for dep in task.get("dependencies", []):
            if dep not in task_id_set:
                findings.append(LintFinding(
                    severity=LintSeverity.ERROR,
                    code="UNKNOWN_DEPENDENCY",
                    message=f"task {task['task_id']} depends on unknown task '{dep}'",
                    task_id=task["task_id"],
                ))
    
    has_errors = any(f.severity == LintSeverity.ERROR for f in findings)
    
    normalized_plan: dict[str, Any] | None = None
    if not has_errors:
        normalized_plan = {
            "spec": plan.get("spec", "").strip() if isinstance(plan.get("spec"), str) else "",
            "project_id": plan.get("project_id", ""),
            "build_id": plan.get("build_id", ""),
            "tasks": normalized_tasks,
        }
    
    return LintResult(
        valid=not has_errors,
        findings=findings,
        normalized_plan=normalized_plan,
    )

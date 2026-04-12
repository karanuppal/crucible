from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from crucible.runtime.run_store import TaskAttemptRecord


@dataclass
class ExecutionPacket:
    packet_id: str
    run_id: str
    task_id: str
    attempt_series: int
    task: dict[str, Any]
    repo_context: dict[str, Any]
    policy_snapshot: dict[str, Any]
    validation_inputs: dict[str, Any]
    history: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2, sort_keys=True)


@dataclass
class StructuredExecutionResult:
    run_id: str
    task_id: str
    status: str
    terminal: bool
    terminal_reason: str
    recommended_transition: str
    attempt_count: int
    final_attempt_id: str
    current_bugfix_state: str = ""
    summary: str = ""
    artifact_refs: dict[str, Any] = field(default_factory=dict)
    metrics: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


RELEVANT_FILE_SUFFIXES = {
    ".py", ".ts", ".tsx", ".js", ".jsx", ".rs", ".go", ".java", ".c", ".cpp", ".h", ".hpp", ".md", ".json", ".yaml", ".yml"
}


def summarize_repo_context(workspace_root: str, task: dict[str, Any], *, max_files: int = 12) -> dict[str, Any]:
    root = Path(workspace_root)
    relevant_files = _extract_relevant_files(root, task, max_files=max_files)
    return {
        "workspace_path": str(root),
        "repo_summary": {
            "root_name": root.name,
            "exists": root.exists(),
            "relevant_file_count": len(relevant_files),
        },
        "relevant_files": relevant_files,
    }


def _extract_relevant_files(root: Path, task: dict[str, Any], *, max_files: int) -> list[str]:
    explicit: list[str] = []
    seen: set[str] = set()
    criteria = task.get("criteria", []) if isinstance(task.get("criteria"), list) else []
    for criterion in criteria:
        triple = criterion.get("triple") if isinstance(criterion.get("triple"), dict) else {}
        build_target = str(triple.get("build_target") or "").strip()
        if build_target:
            normalized = build_target.lstrip("./")
            if normalized not in seen:
                explicit.append(normalized)
                seen.add(normalized)
    if explicit:
        return explicit[:max_files]

    if not root.exists():
        return []

    tokens = {token.lower() for token in str(task.get("description") or "").replace("/", " ").replace("_", " ").split() if len(token) >= 3}
    matches: list[str] = []
    for path in sorted(root.rglob("*")):
        if len(matches) >= max_files:
            break
        if not path.is_file() or path.suffix.lower() not in RELEVANT_FILE_SUFFIXES:
            continue
        rel = path.relative_to(root).as_posix()
        parts = {part.lower() for part in rel.replace("/", " ").replace("_", " ").replace("-", " ").split()}
        if tokens and tokens.isdisjoint(parts):
            continue
        matches.append(rel)
    return matches[:max_files]


def build_execution_packet(
    *,
    run_id: str,
    task: dict[str, Any],
    attempt_id: str,
    attempt_series: int,
    workspace_root: str,
    prior_attempts: list[TaskAttemptRecord],
    prior_evidence_refs: list[str],
    strategy_memory_ref: str | None = None,
) -> ExecutionPacket:
    repo_context = summarize_repo_context(workspace_root, task)
    required_commands = []
    criteria = task.get("criteria", []) if isinstance(task.get("criteria"), list) else []
    must_pass = []
    for criterion in criteria:
        triple = criterion.get("triple") if isinstance(criterion.get("triple"), dict) else {}
        command = str(triple.get("verification_command") or "").strip()
        if command:
            required_commands.append(command)
        if criterion.get("criterion_class", "must_pass") == "must_pass":
            crit_id = str(criterion.get("criterion_id") or "").strip()
            if crit_id:
                must_pass.append(crit_id)
    policy_snapshot = {
        "prompt_family": f"{task.get('role', 'builder')}-standard",
        "model_route": "default",
        "attempt_budget": 4,
        "tool_scope": ["git", "pytest", "shell"],
        "review_tier": "standard" if task.get("review_required", task.get("role", "builder") != "researcher") else "none",
    }
    packet_task = {
        "task_type": str(task.get("role") or "builder"),
        "goal": str(task.get("description") or ""),
        "acceptance_criteria": must_pass or [str(task.get("description") or "")],
    }
    history = {
        "prior_attempt_ids": [attempt.attempt_id for attempt in prior_attempts],
        "prior_failure_packets": [attempt.failure_packet_ref for attempt in prior_attempts if attempt.failure_packet_ref],
        "prior_evidence_refs": list(prior_evidence_refs),
        "strategy_memory_ref": strategy_memory_ref,
    }
    return ExecutionPacket(
        packet_id=f"xp-{task['task_id']}-{attempt_series:02d}",
        run_id=run_id,
        task_id=task["task_id"],
        attempt_series=attempt_series,
        task=packet_task,
        repo_context=repo_context,
        policy_snapshot=policy_snapshot,
        validation_inputs={
            "required_commands": required_commands,
            "must_pass": must_pass,
        },
        history=history,
    )

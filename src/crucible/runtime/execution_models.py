from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from crucible.runtime.run_store import TaskAttemptRecord


STRATEGY_MEMORY_FILENAME = "strategy-memory.json"
REPO_SUMMARY_FILENAME = "repo_summary.json"
BUGFIX_TASK_TYPES = {"bugfix"}
REVIEW_POLICY_TIERS = {"none", "standard", "strict"}
PROMPT_AUDIT_PREFIX = "prompt-audit-"
VALIDATOR_CHAIN_PREFIX = "validator-chain-"


@dataclass
class PromptAuditRecord:
    audit_id: str
    run_id: str
    task_id: str
    attempt_id: str
    attempt_type: str
    prompt_policy: dict[str, Any]
    prompt_instantiation: dict[str, Any]
    model_execution: dict[str, Any]
    result: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ValidatorChainArtifact:
    artifact_id: str
    run_id: str
    task_id: str
    attempt_id: str
    review_policy: dict[str, Any]
    validation_policy: dict[str, Any]
    results: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


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
        "repo_summary": build_repo_summary(root, relevant_files),
        "relevant_files": relevant_files,
    }


def build_repo_summary(root: Path, relevant_files: list[str]) -> dict[str, Any]:
    return {
        "root_name": root.name,
        "exists": root.exists(),
        "relevant_file_count": len(relevant_files),
    }


def persist_repo_summary_artifact(run_root: str, task_id: str, repo_context: dict[str, Any]) -> str:
    repo_summary = dict(repo_context.get("repo_summary") or {})
    payload = {
        "task_id": task_id,
        "workspace_path": repo_context.get("workspace_path", ""),
        "repo_summary": repo_summary,
        "relevant_files": list(repo_context.get("relevant_files") or []),
    }
    path = Path(run_root) / "artifacts" / task_id / REPO_SUMMARY_FILENAME
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True))
    return str(path.relative_to(Path(run_root)))


def ensure_strategy_memory_artifact(
    run_root: str,
    task_id: str,
    *,
    run_id: str,
    prior_attempts: list[TaskAttemptRecord],
) -> str:
    path = Path(run_root) / "artifacts" / task_id / STRATEGY_MEMORY_FILENAME
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        payload = {
            "task_id": task_id,
            "run_id": run_id,
            "entries": [],
            "current_hypotheses": [],
            "prior_attempt_ids": [attempt.attempt_id for attempt in prior_attempts],
            "current_bugfix_state": "investigating",
            "reproduction": {
                "status": "missing",
                "evidence_refs": [],
                "summary": "",
                "reproduction_not_possible": None,
            },
            "phase": "phase-3",
        }
        path.write_text(json.dumps(payload, indent=2, sort_keys=True))
    return str(path.relative_to(Path(run_root)))


def load_strategy_memory_artifact(run_root: str, strategy_memory_ref: str | None) -> dict[str, Any]:
    if not strategy_memory_ref:
        return {}
    path = Path(run_root) / strategy_memory_ref
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text())
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def persist_strategy_memory_artifact(run_root: str, strategy_memory_ref: str, payload: dict[str, Any]) -> None:
    path = Path(run_root) / strategy_memory_ref
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True))


def normalize_review_policy(task: dict[str, Any]) -> dict[str, Any]:
    review_policy = task.get("review_policy") if isinstance(task.get("review_policy"), dict) else {}
    required = review_policy.get("required")
    if not isinstance(required, bool):
        required = bool(task.get("review_required", task.get("role", "builder") != "researcher"))
    tier = str(review_policy.get("tier") or ("standard" if required else "none")).strip().lower()
    if tier not in REVIEW_POLICY_TIERS:
        tier = "standard" if required else "none"
    return {"required": required, "tier": tier}


def build_validation_policy(task: dict[str, Any]) -> dict[str, Any]:
    criteria = task.get("criteria", []) if isinstance(task.get("criteria"), list) else []
    required_commands: list[str] = []
    must_pass: list[str] = []
    informational: list[str] = []
    for criterion in criteria:
        triple = criterion.get("triple") if isinstance(criterion.get("triple"), dict) else {}
        command = str(triple.get("verification_command") or "").strip()
        if command:
            required_commands.append(command)
        criterion_id = str(criterion.get("criterion_id") or "").strip()
        if not criterion_id:
            continue
        if criterion.get("criterion_class", "must_pass") == "must_pass":
            must_pass.append(criterion_id)
        else:
            informational.append(criterion_id)
    return {
        "required_commands": required_commands,
        "must_pass": must_pass,
        "informational": informational,
    }


def persist_prompt_audit_record(run_root: str, task_id: str, attempt_id: str, payload: dict[str, Any]) -> str:
    path = Path(run_root) / "artifacts" / task_id / f"{PROMPT_AUDIT_PREFIX}{attempt_id}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True))
    return str(path.relative_to(Path(run_root)))


def persist_validator_chain_artifact(run_root: str, task_id: str, attempt_id: str, payload: dict[str, Any]) -> str:
    path = Path(run_root) / "artifacts" / task_id / f"{VALIDATOR_CHAIN_PREFIX}{attempt_id}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True))
    return str(path.relative_to(Path(run_root)))


def is_bugfix_task(task: dict[str, Any]) -> bool:
    task_type = str(task.get("task_type") or task.get("role") or "").strip().lower()
    return task_type in BUGFIX_TASK_TYPES


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


def evaluate_retry_admission(
    *,
    attempt_series: int,
    prior_evidence_refs: list[str],
    strategy_memory: dict[str, Any] | None,
) -> dict[str, Any]:
    strategy_memory = dict(strategy_memory or {})
    rejected_entries = [
        entry for entry in strategy_memory.get("entries", [])
        if isinstance(entry, dict) and entry.get("do_not_repeat_without_change")
    ]
    required_deltas = [
        str(entry.get("required_delta_for_retry") or "").strip()
        for entry in rejected_entries
        if str(entry.get("required_delta_for_retry") or "").strip()
    ]
    if attempt_series <= 1 or not rejected_entries:
        return {
            "admitted": True,
            "reason": "first_attempt_or_no_rejections",
            "required_deltas": required_deltas,
            "new_evidence_refs": [],
        }

    known_refs = {
        str(ref)
        for entry in rejected_entries
        for ref in (entry.get("evidence_refs") or [])
        if str(ref)
    }
    current_refs = {str(ref) for ref in prior_evidence_refs if str(ref)}
    new_evidence_refs = sorted(current_refs - known_refs)
    if new_evidence_refs:
        return {
            "admitted": True,
            "reason": "new_durable_evidence_since_rejection",
            "required_deltas": required_deltas,
            "new_evidence_refs": new_evidence_refs,
        }
    if required_deltas:
        return {
            "admitted": False,
            "reason": "required_delta_for_retry_not_structurally_satisfied",
            "required_deltas": required_deltas,
            "new_evidence_refs": [],
        }
    return {
        "admitted": True,
        "reason": "no_required_delta_declared",
        "required_deltas": [],
        "new_evidence_refs": [],
    }


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
    strategy_memory: dict[str, Any] | None = None,
    repo_context: dict[str, Any] | None = None,
) -> ExecutionPacket:
    repo_context = dict(repo_context) if repo_context is not None else summarize_repo_context(workspace_root, task)
    validation_policy = build_validation_policy(task)
    review_policy = normalize_review_policy(task)
    required_commands = list(validation_policy["required_commands"])
    must_pass = list(validation_policy["must_pass"])
    policy_snapshot = {
        "prompt_family": f"{task.get('role', 'builder')}-standard",
        "model_route": "default",
        "attempt_budget": 4,
        "tool_scope": ["git", "pytest", "shell"],
        "review_tier": review_policy["tier"],
        "review_required": review_policy["required"],
    }
    packet_task = {
        "task_type": str(task.get("role") or "builder"),
        "goal": str(task.get("description") or ""),
        "acceptance_criteria": must_pass or [str(task.get("description") or "")],
    }
    strategy_memory = dict(strategy_memory or {})
    rejected_entries = [
        entry for entry in strategy_memory.get("entries", [])
        if isinstance(entry, dict) and entry.get("do_not_repeat_without_change")
    ]
    retry_admission = evaluate_retry_admission(
        attempt_series=attempt_series,
        prior_evidence_refs=prior_evidence_refs,
        strategy_memory=strategy_memory,
    )
    history = {
        "prior_attempt_ids": [attempt.attempt_id for attempt in prior_attempts],
        "prior_failure_packets": [attempt.failure_packet_ref for attempt in prior_attempts if attempt.failure_packet_ref],
        "prior_evidence_refs": list(prior_evidence_refs),
        "strategy_memory_ref": strategy_memory_ref,
        "strategy_memory": strategy_memory,
        "current_bugfix_state": strategy_memory.get("current_bugfix_state", ""),
        "retry_guardrails": {
            "rejected_strategy_count": len(rejected_entries),
            "must_materially_differ": bool(rejected_entries),
            "required_deltas": [str(entry.get("required_delta_for_retry") or "") for entry in rejected_entries if str(entry.get("required_delta_for_retry") or "")],
        },
        "retry_admission": retry_admission,
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

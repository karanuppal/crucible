"""Phase 8 §26: Durable run store.

Each `crucible run` invocation produces a directory under `runs/<run_id>/`
with:
  run.json          - RunManifest
  tasks.json        - intake task plan snapshot
  events.jsonl      - append-only RunEvent stream
  result.json       - final RunSummary (terminal state only)
  adapter.log       - backend selection / failover trace
  adapter-state/    - per-handle persisted adapter state (event bridge)
  attempts/         - TaskAttemptRecord JSON files keyed by attempt_id
  artifacts.json    - artifact manifest with content hashes
  artifacts/        - materialized artifact payloads / refs

The run store augments — does not replace — the Phase 1 ledger.
"""

from __future__ import annotations

import json
import os
import time
import uuid
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Any


# ─────────────────────────────────────────────────────────────────
# Schema (matches v5.3 §26.2)
# ─────────────────────────────────────────────────────────────────

RunStatusLiteral = str  # "running" | "blocked" | "complete" | "failed" | "partial"
TerminalStatusLiteral = str  # "complete" | "failed" | "blocked" | "partial" | "cancelled"


@dataclass
class RunManifest:
    run_id: str
    project_id: str
    build_id: str
    run_root: str
    created_at: float
    spec_text_hash: str
    task_definitions_hash: str
    current_phase: str
    current_status: RunStatusLiteral
    cli_version: str
    embedding_surface: str = ""
    embedding_session_ref: str = ""
    ledger_ref: str = ""
    workspace_root: str = ""
    plan_ref: str = ""
    plan_status: str = "missing"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "RunManifest":
        # Backward-compat: ignore unknown fields and supply defaults for any
        # missing fields. This lets old runs load with newer code (or vice
        # versa) without crashing.
        import dataclasses as _dc
        known = {f.name for f in _dc.fields(cls)}
        filtered = {k: v for k, v in data.items() if k in known}
        return cls(**filtered)


@dataclass
class RunEvent:
    event_id: str
    run_id: str
    timestamp: float
    type: str
    task_id: str = ""
    attempt_id: str = ""
    payload: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "RunEvent":
        return cls(
            event_id=data["event_id"],
            run_id=data["run_id"],
            timestamp=data["timestamp"],
            type=data["type"],
            task_id=data.get("task_id", ""),
            attempt_id=data.get("attempt_id", ""),
            payload=data.get("payload", {}),
        )


@dataclass
class TaskAttemptRecord:
    attempt_id: str
    task_id: str
    attempt_index: int
    backend_id: str
    status: str  # AdapterStatus value
    needs_reconciliation: bool = False
    workspace_ref: str = ""
    winning_attempt: bool = False
    artifact_paths: list[str] = field(default_factory=list)
    blockers: list[str] = field(default_factory=list)
    started_at: float = 0.0
    finished_at: float | None = None
    error: str = ""
    is_partial: bool = False
    resume_token: str = ""
    attempt_type: str = "build"
    parent_attempt_id: str = ""
    derived_from_attempt_ids: list[str] = field(default_factory=list)
    workspace_id: str = ""
    workspace_mode: str = "fresh"
    failure_packet_ref: str = ""
    result_evidence_refs: list[str] = field(default_factory=list)
    review_verdict: str = ""
    supersedes_attempt_id: str = ""
    superseded_by_attempt_id: str = ""
    next_action_chosen: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "TaskAttemptRecord":
        return cls(
            attempt_id=data["attempt_id"],
            task_id=data["task_id"],
            attempt_index=data.get("attempt_index", 0),
            backend_id=data.get("backend_id", ""),
            status=data.get("status", "pending"),
            needs_reconciliation=data.get("needs_reconciliation", False),
            workspace_ref=data.get("workspace_ref", ""),
            winning_attempt=data.get("winning_attempt", False),
            artifact_paths=list(data.get("artifact_paths", [])),
            blockers=list(data.get("blockers", [])),
            started_at=data.get("started_at", 0.0),
            finished_at=data.get("finished_at"),
            error=data.get("error", ""),
            is_partial=data.get("is_partial", False),
            resume_token=data.get("resume_token", ""),
            attempt_type=data.get("attempt_type", "build"),
            parent_attempt_id=data.get("parent_attempt_id", ""),
            derived_from_attempt_ids=list(data.get("derived_from_attempt_ids", [])),
            workspace_id=data.get("workspace_id", ""),
            workspace_mode=data.get("workspace_mode", "fresh"),
            failure_packet_ref=data.get("failure_packet_ref", ""),
            result_evidence_refs=list(data.get("result_evidence_refs", [])),
            review_verdict=data.get("review_verdict", ""),
            supersedes_attempt_id=data.get("supersedes_attempt_id", ""),
            superseded_by_attempt_id=data.get("superseded_by_attempt_id", ""),
            next_action_chosen=data.get("next_action_chosen", ""),
            metadata=data.get("metadata", {}),
        )


@dataclass
class CostSummary:
    backends_used: list[str] = field(default_factory=list)
    total_wall_clock_seconds: float = 0.0
    retries_total: int = 0
    subagents_spawned: int = 0
    estimated_tokens: int | None = None
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class RunSummary:
    run_id: str
    terminal_status: TerminalStatusLiteral
    completed_tasks: list[str] = field(default_factory=list)
    failed_tasks: list[str] = field(default_factory=list)
    partial_tasks: list[str] = field(default_factory=list)
    blocked_reason: str = ""
    integration_status: str | None = None
    cost_summary: CostSummary | None = None
    total_runtime_seconds: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        d = {
            "run_id": self.run_id,
            "terminal_status": self.terminal_status,
            "completed_tasks": list(self.completed_tasks),
            "failed_tasks": list(self.failed_tasks),
            "partial_tasks": list(self.partial_tasks),
            "blocked_reason": self.blocked_reason,
            "integration_status": self.integration_status,
            "total_runtime_seconds": self.total_runtime_seconds,
        }
        if self.cost_summary is not None:
            d["cost_summary"] = self.cost_summary.to_dict()
        return d


# ─────────────────────────────────────────────────────────────────
# Run store
# ─────────────────────────────────────────────────────────────────

CRUCIBLE_CLI_VERSION = "0.1.0"


def default_runs_root() -> str:
    """Return the absolute path to the default runs directory.
    
    Round-7 fix: always return an absolute path so manifest.run_root is
    never relative regardless of how the env var or default was set.
    """
    raw = os.environ.get("CRUCIBLE_RUNS_DIR", os.path.join(os.getcwd(), "runs"))
    return os.path.abspath(raw)


def new_run_id() -> str:
    return f"run-{uuid.uuid4().hex[:12]}"


def _atomic_write_json(path: str, data: Any) -> None:
    """Write JSON atomically. Uses a per-call unique tmp file so concurrent
    writers don't collide on a shared path.tmp."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = f"{path}.{os.getpid()}.{uuid.uuid4().hex[:8]}.tmp"
    try:
        with open(tmp, "w") as f:
            json.dump(data, f, indent=2)
            f.flush()
            try:
                os.fsync(f.fileno())
            except OSError:
                pass
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _hash_text(text: str) -> str:
    import hashlib
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


class RunLockError(Exception):
    """Raised when a run is already locked by another process."""


class RunStore:
    """Filesystem-backed durable store for one Crucible run.
    
    Authoritative state for `crucible status`, `watch`, `resume`.
    """
    
    def __init__(self, run_root: str) -> None:
        self._run_root = os.path.abspath(run_root)
        os.makedirs(self._run_root, exist_ok=True)
        os.makedirs(os.path.join(self._run_root, "adapter-state"), exist_ok=True)
        os.makedirs(os.path.join(self._run_root, "attempts"), exist_ok=True)
        os.makedirs(os.path.join(self._run_root, "artifacts"), exist_ok=True)
        self._lock_fd: int | None = None
    
    @property
    def run_root(self) -> str:
        return self._run_root
    
    @property
    def lock_path(self) -> str:
        return os.path.join(self._run_root, "run.lock")
    
    def acquire_lock(self) -> None:
        """Acquire an exclusive write lock on this run.
        
        Raises RunLockError if another process holds the lock.
        Uses fcntl.flock on POSIX. Auto-released when the process exits
        or release_lock() is called.
        """
        import fcntl
        if self._lock_fd is not None:
            return  # already held by this instance
        fd = os.open(self.lock_path, os.O_WRONLY | os.O_CREAT, 0o644)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except (BlockingIOError, OSError) as e:
            os.close(fd)
            raise RunLockError(
                f"run {os.path.basename(self._run_root)} is already locked by another process"
            ) from e
        # Write our pid for debugging
        try:
            os.ftruncate(fd, 0)
            os.write(fd, f"{os.getpid()}\n".encode())
        except OSError:
            pass
        self._lock_fd = fd
    
    def release_lock(self) -> None:
        if self._lock_fd is None:
            return
        import fcntl
        try:
            fcntl.flock(self._lock_fd, fcntl.LOCK_UN)
        except OSError:
            pass
        try:
            os.close(self._lock_fd)
        except OSError:
            pass
        self._lock_fd = None
    
    def __enter__(self) -> "RunStore":
        return self
    
    def __exit__(self, *args) -> None:
        self.release_lock()
    
    @property
    def manifest_path(self) -> str:
        return os.path.join(self._run_root, "run.json")
    
    @property
    def tasks_path(self) -> str:
        return os.path.join(self._run_root, "tasks.json")

    @property
    def plan_path(self) -> str:
        return os.path.join(self._run_root, "plan.json")
    
    @property
    def events_path(self) -> str:
        return os.path.join(self._run_root, "events.jsonl")
    
    @property
    def result_path(self) -> str:
        return os.path.join(self._run_root, "result.json")
    
    @property
    def adapter_log_path(self) -> str:
        return os.path.join(self._run_root, "adapter.log")
    
    @property
    def artifacts_manifest_path(self) -> str:
        return os.path.join(self._run_root, "artifacts.json")
    
    def adapter_state_path(self, handle_id: str) -> str:
        return os.path.join(self._run_root, "adapter-state", f"{handle_id}.json")
    
    def attempt_path(self, attempt_id: str) -> str:
        return os.path.join(self._run_root, "attempts", f"{attempt_id}.json")
    
    # ─── Manifest ───
    
    def write_manifest(self, manifest: RunManifest) -> None:
        # Round-6 fix: canonicalize workspace_root at every write so a
        # manifest can never end up with a relative or non-canonical path.
        if manifest.workspace_root:
            manifest.workspace_root = _canonicalize_workspace(manifest.workspace_root)
        _atomic_write_json(self.manifest_path, manifest.to_dict())
    
    def read_manifest(self) -> RunManifest | None:
        if not os.path.isfile(self.manifest_path):
            return None
        with open(self.manifest_path) as f:
            manifest = RunManifest.from_dict(json.load(f))
        # Round-6 fix: any non-canonical workspace_root on disk (e.g. left
        # over by an older Crucible version or hand-edited) is canonicalized
        # at read time so downstream code never sees an ambiguous relative path.
        if manifest.workspace_root:
            canonical = _canonicalize_workspace(manifest.workspace_root)
            if canonical != manifest.workspace_root:
                manifest.workspace_root = canonical
                # Persist the canonical form back to disk so future reads are stable.
                # Best-effort: don't fail read if write fails (e.g. read-only fs).
                try:
                    _atomic_write_json(self.manifest_path, manifest.to_dict())
                except OSError:
                    pass
        return manifest
    
    def update_manifest_status(self, current_phase: str, current_status: str) -> None:
        m = self.read_manifest()
        if m is None:
            return
        m.current_phase = current_phase
        m.current_status = current_status
        self.write_manifest(m)
    
    # ─── Tasks snapshot ───
    
    def write_tasks_snapshot(self, plan: dict[str, Any]) -> None:
        _atomic_write_json(self.tasks_path, plan)
    
    def read_tasks_snapshot(self) -> dict[str, Any] | None:
        if not os.path.isfile(self.tasks_path):
            return None
        with open(self.tasks_path) as f:
            return json.load(f)
    
    # ─── Durable plan artifact ───

    def write_plan(self, plan: dict[str, Any]) -> None:
        _atomic_write_json(self.plan_path, plan)
        manifest = self.read_manifest()
        if manifest is not None:
            manifest.plan_ref = self.plan_path
            manifest.plan_status = str(plan.get("status") or "missing")
            self.write_manifest(manifest)

    def read_plan(self) -> dict[str, Any] | None:
        if not os.path.isfile(self.plan_path):
            return None
        with open(self.plan_path) as f:
            return json.load(f)

    # ─── Events ───
    
    def append_event(
        self,
        event_type: str,
        *,
        task_id: str = "",
        attempt_id: str = "",
        payload: dict[str, Any] | None = None,
    ) -> RunEvent:
        manifest = self.read_manifest()
        run_id = manifest.run_id if manifest else "unknown"
        event = RunEvent(
            event_id=f"evt-{uuid.uuid4().hex[:10]}",
            run_id=run_id,
            timestamp=time.time(),
            type=event_type,
            task_id=task_id,
            attempt_id=attempt_id,
            payload=payload or {},
        )
        line = json.dumps(event.to_dict(), separators=(",", ":"))
        with open(self.events_path, "a") as f:
            f.write(line + "\n")
        return event
    
    def read_events(self, *, from_event_id: str | None = None) -> list[RunEvent]:
        """Read all events, optionally starting from a specific event_id.
        
        from_event_id semantics:
          None or "0" → read all events from the beginning
          <event_id>  → read events from that event onward (inclusive)
        """
        if not os.path.isfile(self.events_path):
            return []
        events: list[RunEvent] = []
        all_events: list[RunEvent] = []
        with open(self.events_path) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    e = RunEvent.from_dict(json.loads(line))
                except (json.JSONDecodeError, KeyError):
                    continue
                all_events.append(e)
        
        if from_event_id is None or from_event_id == "0":
            return all_events
        
        # Filter from a specific event_id onward
        result: list[RunEvent] = []
        seen = False
        for e in all_events:
            if not seen and e.event_id == from_event_id:
                seen = True
            if seen:
                result.append(e)
        return result
    
    # ─── Attempts ───
    
    def write_attempt(self, attempt: TaskAttemptRecord) -> None:
        _atomic_write_json(self.attempt_path(attempt.attempt_id), attempt.to_dict())
    
    def read_attempt(self, attempt_id: str) -> TaskAttemptRecord | None:
        path = self.attempt_path(attempt_id)
        if not os.path.isfile(path):
            return None
        with open(path) as f:
            return TaskAttemptRecord.from_dict(json.load(f))
    
    def list_attempts(self) -> list[TaskAttemptRecord]:
        attempts_dir = os.path.join(self._run_root, "attempts")
        if not os.path.isdir(attempts_dir):
            return []
        records: list[TaskAttemptRecord] = []
        for fname in sorted(os.listdir(attempts_dir)):
            if not fname.endswith(".json"):
                continue
            try:
                with open(os.path.join(attempts_dir, fname)) as f:
                    records.append(TaskAttemptRecord.from_dict(json.load(f)))
            except (json.JSONDecodeError, KeyError):
                continue
        return sorted(records, key=lambda record: (record.task_id, record.attempt_index, record.attempt_id))

    def attempts_for_task(self, task_id: str) -> list[TaskAttemptRecord]:
        attempts = [a for a in self.list_attempts() if a.task_id == task_id]
        return sorted(attempts, key=lambda record: (record.attempt_index, record.attempt_id))
    
    def reconcile_in_flight_attempts(self) -> list[TaskAttemptRecord]:
        """After restart, mark any non-terminal attempts as needing reconciliation.
        
        Returns the attempts that were marked.
        """
        from crucible.accelerators.adapters import AdapterStatus
        terminal = {
            AdapterStatus.COMPLETE.value,
            AdapterStatus.FAILED.value,
            AdapterStatus.KILLED.value,
            AdapterStatus.TIMED_OUT.value,
            AdapterStatus.PARTIAL.value,
        }
        flagged: list[TaskAttemptRecord] = []
        for a in self.list_attempts():
            if a.status not in terminal and not a.needs_reconciliation:
                a.needs_reconciliation = True
                a.blockers.append("post-restart: terminal state not recorded before crash")
                self.write_attempt(a)
                flagged.append(a)
        return flagged
    
    # ─── Result ───
    
    def write_result(self, summary: RunSummary) -> None:
        _atomic_write_json(self.result_path, summary.to_dict())
    
    def read_result(self) -> dict[str, Any] | None:
        if not os.path.isfile(self.result_path):
            return None
        with open(self.result_path) as f:
            return json.load(f)
    
    def is_terminal(self) -> bool:
        return os.path.isfile(self.result_path)
    
    # ─── Adapter state (event-bridge cache) ───
    
    def write_adapter_state(self, handle_id: str, state: dict[str, Any]) -> None:
        _atomic_write_json(self.adapter_state_path(handle_id), state)
    
    def read_adapter_state(self, handle_id: str) -> dict[str, Any] | None:
        path = self.adapter_state_path(handle_id)
        if not os.path.isfile(path):
            return None
        with open(path) as f:
            return json.load(f)
    
    def list_adapter_handles(self) -> list[str]:
        d = os.path.join(self._run_root, "adapter-state")
        if not os.path.isdir(d):
            return []
        return [fn[:-5] for fn in sorted(os.listdir(d)) if fn.endswith(".json")]
    
    # ─── Artifact manifest ───
    
    def write_artifact_manifest(self, entries: list[dict[str, Any]]) -> None:
        _atomic_write_json(self.artifacts_manifest_path, {"entries": entries})
    
    def read_artifact_manifest(self) -> list[dict[str, Any]]:
        if not os.path.isfile(self.artifacts_manifest_path):
            return []
        with open(self.artifacts_manifest_path) as f:
            return json.load(f).get("entries", [])
    
    # ─── Adapter log (free-form lines) ───
    
    def append_adapter_log(self, line: str) -> None:
        with open(self.adapter_log_path, "a") as f:
            f.write(f"{time.time():.3f} {line}\n")


def _canonicalize_workspace(path: str) -> str:
    """Resolve a workspace path to its canonical absolute form.
    
    Strips trailing slashes, resolves symlinks via realpath, and makes
    the path absolute. Returns "" if input is empty/falsy.
    
    This is the single source of truth for how workspace_root is stored
    in the manifest. Both create-time and resume-override paths must
    flow through this function so that comparisons and pinning are
    consistent regardless of how the user typed the path.
    """
    if not path:
        return ""
    return os.path.realpath(os.path.abspath(path))


def create_run_store(
    *,
    run_id: str | None,
    project_id: str,
    build_id: str,
    spec_text: str,
    task_plan: dict[str, Any],
    embedding_surface: str = "",
    embedding_session_ref: str = "",
    runs_root: str | None = None,
    ledger_ref: str = "",
    workspace_root: str = "",
    persist_validated_plan: bool = True,
) -> tuple[RunStore, RunManifest]:
    """Create a fresh run directory and return (store, manifest)."""
    if run_id is None:
        run_id = new_run_id()
    if runs_root is None:
        runs_root = default_runs_root()
    # Round-7 fix: always store an absolute run_root in the manifest so
    # downstream code never has to guess what cwd was at create time.
    runs_root = os.path.abspath(runs_root)
    run_root = os.path.join(runs_root, run_id)
    store = RunStore(run_root)
    manifest = RunManifest(
        run_id=run_id,
        project_id=project_id,
        build_id=build_id,
        run_root=run_root,
        created_at=time.time(),
        spec_text_hash=_hash_text(spec_text),
        task_definitions_hash=_hash_text(json.dumps(task_plan, sort_keys=True)),
        current_phase="intake",
        current_status="running",
        cli_version=CRUCIBLE_CLI_VERSION,
        embedding_surface=embedding_surface,
        embedding_session_ref=embedding_session_ref,
        ledger_ref=ledger_ref,
        workspace_root=_canonicalize_workspace(workspace_root),
        plan_ref=os.path.join(run_root, "plan.json"),
        plan_status="missing",
    )
    store.write_manifest(manifest)
    store.write_tasks_snapshot(task_plan)
    if task_plan and persist_validated_plan:
        from crucible.planning import PlanningError, build_plan_artifact

        try:
            durable_plan = build_plan_artifact(
                run_id=run_id,
                submitted_plan=task_plan,
                embedding_surface=embedding_surface,
                embedding_session_ref=embedding_session_ref,
            )
        except PlanningError as e:
            manifest.plan_status = "invalid"
            store.write_manifest(manifest)
            store.append_event("plan_invalid", payload={"error": str(e)})
            raise
        store.write_plan(durable_plan)
    store.append_event("run_started", payload={"run_id": run_id, "project_id": project_id})
    return store, manifest


def load_run_store(run_id: str, runs_root: str | None = None) -> RunStore | None:
    if runs_root is None:
        runs_root = default_runs_root()
    runs_root = os.path.abspath(runs_root)
    run_root = os.path.join(runs_root, run_id)
    if not os.path.isdir(run_root):
        return None
    return RunStore(run_root)

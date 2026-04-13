"""OpenClaw tool wrapper for Crucible.

This module exposes `crucible` as an OpenClaw tool. The contract:

Input (dict):
  plan: dict           # required for run/lint
  mode: str            # run|lint|status|watch|resume
  run_id: str          # required for status/watch/resume
  detach: bool
  embedding_surface: str
  embedding_session_ref: str
  workspace_root: str  # where verification commands run
  runs_dir: str        # override CRUCIBLE_RUNS_DIR

Output (dict):
  status: str          # ok|error|lint_failed|terminal
  exit_code: int
  run_id: str          # always present after run/resume/detach
  run_root: str        # always present after run/resume/detach
  terminal_status: str # run_succeeded|run_failed|run_blocked|run_escalated|run_cancelled (when terminal)
  message: str         # human-readable error
  events: list         # for watch
  findings: list       # for lint failures
  raw_stdout: str      # only on parse failures, for debugging

The wrapper forces structured CLI output (--jsonl/--json) and never
relies on parsing human-readable lines. If a CLI command's structured
output is missing or malformed, the wrapper returns status=error.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import threading
from typing import Any, Callable

from crucible.planning import (
    PlanningError,
    build_plan_artifact,
    detect_ambiguity,
    ensure_validated_plan,
)
from crucible.runtime.statuses import RunTerminalStatus, legacy_run_status


TOOL_NAME = "crucible"
TOOL_VERSION = "0.2.0"


def run(input_json: dict[str, Any]) -> dict[str, Any]:
    payload = dict(input_json)
    payload["mode"] = "run"
    return execute(payload)


def lint(input_json: dict[str, Any]) -> dict[str, Any]:
    payload = dict(input_json)
    payload["mode"] = "lint"
    return execute(payload)


def status(input_json: dict[str, Any]) -> dict[str, Any]:
    payload = dict(input_json)
    payload["mode"] = "status"
    return execute(payload)


def watch(input_json: dict[str, Any]) -> dict[str, Any]:
    payload = dict(input_json)
    payload["mode"] = "watch"
    return execute(payload)


def resume(input_json: dict[str, Any]) -> dict[str, Any]:
    payload = dict(input_json)
    payload["mode"] = "resume"
    return execute(payload)


def _cli_command() -> list[str]:
    """Build the CLI invocation command."""
    cli_path = os.environ.get("CRUCIBLE_CLI_PATH")
    if cli_path:
        return [cli_path]
    return [sys.executable, "-m", "crucible.runtime.cli"]


def _cli_env(input_json: dict[str, Any]) -> dict[str, str]:
    env = os.environ.copy()
    if input_json.get("embedding_session_ref"):
        env["CRUCIBLE_EMBEDDING_SESSION_REF"] = str(input_json["embedding_session_ref"])
    if input_json.get("embedding_surface"):
        env["CRUCIBLE_EMBEDDING_SURFACE"] = str(input_json["embedding_surface"])
    if input_json.get("workspace_root"):
        env["CRUCIBLE_WORKSPACE_ROOT"] = str(input_json["workspace_root"])
    return env


def _execute(args: list[str], env: dict[str, str], timeout: int) -> tuple[int, str, str]:
    base = _cli_command()
    try:
        result = subprocess.run(
            base + args,
            capture_output=True,
            text=True,
            timeout=timeout,
            env=env,
        )
        return result.returncode, result.stdout, result.stderr
    except FileNotFoundError as e:
        return 5, "", f"crucible CLI not found: {e}"
    except subprocess.TimeoutExpired:
        return 5, "", f"crucible CLI timed out after {timeout}s"


def _parse_jsonl(stdout: str) -> list[dict[str, Any]]:
    """Parse stdout as JSONL — one JSON object per line, ignore blanks."""
    parsed: list[dict[str, Any]] = []
    for line in stdout.split("\n"):
        line = line.strip()
        if not line:
            continue
        try:
            parsed.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return parsed


def _parse_json(stdout: str) -> dict[str, Any] | None:
    """Parse stdout as a single JSON object."""
    try:
        return json.loads(stdout)
    except json.JSONDecodeError:
        return None


def _exit_to_status(exit_code: int) -> str:
    return {
        0: "ok",
        1: "error",
        2: "lint_failed",
        3: "terminal",
        4: "error",
        5: "error",
    }.get(exit_code, "error")


def _derive_semantic_state(current_status: str, attempts: list[dict[str, Any]] | None = None) -> str:
    attempts = attempts or []
    terminal_semantic_map = {
        RunTerminalStatus.SUCCEEDED.value: "complete",
        RunTerminalStatus.FAILED.value: "failed",
        RunTerminalStatus.BLOCKED.value: "blocked",
        RunTerminalStatus.ESCALATED.value: "awaiting_user",
        RunTerminalStatus.CANCELLED.value: "cancelled",
    }
    if current_status in terminal_semantic_map:
        return terminal_semantic_map[current_status]
    if current_status in {"complete", "failed", "blocked", "partial", "cancelled", "awaiting_user"}:
        return current_status
    if any(a.get("needs_reconciliation") for a in attempts):
        return "repairing"
    if any(a.get("is_partial") for a in attempts):
        return "salvaging"
    if any((a.get("metadata") or {}).get("attempt_type") == "debug" for a in attempts):
        return "debugging"
    if any((a.get("metadata") or {}).get("attempt_type") == "review" for a in attempts):
        return "reviewing"
    if attempts:
        return "building"
    return current_status or "queued"


def _resolve_workspace_root(input_json: dict[str, Any]) -> str:
    from crucible.runtime.run_store import _canonicalize_workspace
    return _canonicalize_workspace(
        input_json.get("workspace_root")
        or os.environ.get("CRUCIBLE_WORKSPACE_ROOT")
        or os.getcwd()
    )


def _resolve_adapter_factory(input_json: dict[str, Any]) -> Callable[[Any], list[Any]] | None:
    factory = input_json.get("adapter_factory")
    if callable(factory):
        return factory

    spawn_callable = input_json.get("openclaw_spawn_callable")
    wait_callable = input_json.get("openclaw_wait_callable")
    if callable(spawn_callable) and callable(wait_callable):
        from crucible.runtime.openclaw_bridge import SessionsSpawnBridge, BridgeBackedAdapter

        def _factory(store):
            bridge = SessionsSpawnBridge(
                store,
                spawn_callable=spawn_callable,
                wait_callable=wait_callable,
            )
            return [BridgeBackedAdapter(bridge)]

        return _factory

    return None


# ─────────────────────────────────────────────────────────────────
# Per-mode handlers
# ─────────────────────────────────────────────────────────────────

def _do_lint(input_json: dict[str, Any], runs_dir: str | None) -> dict[str, Any]:
    plan = input_json.get("plan")
    if not isinstance(plan, dict):
        return {"status": "error", "exit_code": 1, "message": "plan dict required for lint mode"}
    
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        json.dump(plan, f)
        plan_path = f.name
    
    try:
        args: list[str] = []
        if runs_dir:
            args.extend(["--runs-dir", runs_dir])
        args.extend(["lint-plan", plan_path, "--json"])
        rc, stdout, stderr = _execute(args, _cli_env(input_json), timeout=30)
    finally:
        try:
            os.unlink(plan_path)
        except OSError:
            pass
    
    out: dict[str, Any] = {"exit_code": rc, "status": _exit_to_status(rc)}
    parsed = _parse_json(stdout)
    if parsed:
        out["valid"] = parsed.get("valid", False)
        out["findings"] = parsed.get("findings", [])
    if stderr:
        out["stderr"] = stderr.strip()
    return out


def _do_run(input_json: dict[str, Any], runs_dir: str | None) -> dict[str, Any]:
    plan = input_json.get("plan")
    if not isinstance(plan, dict):
        return {"status": "error", "exit_code": 1, "message": "plan dict required for run mode"}

    adapter_factory = _resolve_adapter_factory(input_json)
    if adapter_factory is not None:
        from crucible.runtime.preflight import lint_plan
        from crucible.runtime.run_executor import execute_run
        from crucible.runtime.run_store import create_run_store, default_runs_root, RunSummary

        lint = lint_plan(plan)
        if not lint.valid:
            return {
                "status": "lint_failed",
                "exit_code": 2,
                "findings": lint.to_dict().get("findings", []),
            }

        normalized = lint.normalized_plan or plan
        embedding_surface = str(input_json.get("embedding_surface") or os.environ.get("CRUCIBLE_EMBEDDING_SURFACE", ""))
        embedding_session_ref = str(input_json.get("embedding_session_ref") or os.environ.get("CRUCIBLE_EMBEDDING_SESSION_REF", ""))
        workspace_root = _resolve_workspace_root(input_json)
        store, manifest = create_run_store(
            run_id=None,
            project_id=normalized["project_id"],
            build_id=normalized["build_id"],
            spec_text=normalized.get("spec", ""),
            task_plan=normalized,
            embedding_surface=embedding_surface,
            embedding_session_ref=embedding_session_ref,
            runs_root=runs_dir or default_runs_root(),
            workspace_root=workspace_root,
            persist_validated_plan=False,
        )

        ambiguity = detect_ambiguity(normalized)
        if ambiguity.should_escalate:
            store.append_event("run_escalated", payload={"ambiguity": ambiguity.to_dict()})
            manifest.current_phase = "planning"
            manifest.current_status = "escalated"
            store.write_manifest(manifest)
            return {
                "status": "terminal",
                "exit_code": 3,
                "run_id": manifest.run_id,
                "run_root": manifest.run_root,
                "message": "ambiguity requires human clarification",
                "ambiguity": ambiguity.to_dict(),
            }

        durable_plan = build_plan_artifact(
            run_id=manifest.run_id,
            submitted_plan=normalized,
            embedding_surface=embedding_surface,
            embedding_session_ref=embedding_session_ref,
        )
        store.write_plan(durable_plan)
        store.append_event("plan_validated", payload={"plan_ref": store.plan_path, "plan_status": durable_plan["status"]})

        if input_json.get("detach"):
            def _runner() -> None:
                try:
                    ensure_validated_plan(store.read_plan())
                    execute_run(
                        store=store,
                        manifest=manifest,
                        plan=ensure_validated_plan(store.read_plan()),
                        adapter_factory=adapter_factory,
                        workspace_root=workspace_root,
                    )
                except Exception as e:
                    store.append_event("background_run_failed", payload={"error": str(e)})
                    store.write_result(RunSummary(
                        run_id=manifest.run_id,
                        terminal_status=RunTerminalStatus.FAILED.value,
                        blocked_reason=f"background run failed: {e}",
                    ))
                    store.update_manifest_status("done", RunTerminalStatus.FAILED.value)

            thread = threading.Thread(
                target=_runner,
                name=f"crucible-detach-{manifest.run_id}",
                daemon=True,
            )
            thread.start()
            return {
                "status": "ok",
                "exit_code": 0,
                "run_id": manifest.run_id,
                "run_root": manifest.run_root,
                "message": "detached bridge-backed run started",
            }

        ensure_validated_plan(store.read_plan())
        summary = execute_run(
            store=store,
            manifest=manifest,
            plan=ensure_validated_plan(store.read_plan()),
            adapter_factory=adapter_factory,
            workspace_root=workspace_root,
        )
        out = {
            "status": "ok" if summary.terminal_status == RunTerminalStatus.SUCCEEDED.value else "terminal",
            "exit_code": 0 if summary.terminal_status == RunTerminalStatus.SUCCEEDED.value else 3,
            "run_id": manifest.run_id,
            "run_root": manifest.run_root,
            "terminal_status": summary.terminal_status,
            "semantic_state": _derive_semantic_state(summary.terminal_status),
            "plan_status": durable_plan["status"],
            "plan_path": store.plan_path,
            "plan": durable_plan,
            "completed_tasks": summary.completed_tasks,
            "failed_tasks": summary.failed_tasks,
            "partial_tasks": summary.partial_tasks,
            "blocked_reason": summary.blocked_reason,
            "total_runtime_seconds": summary.total_runtime_seconds,
        }
        return out
    
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        json.dump(plan, f)
        plan_path = f.name
    
    try:
        args: list[str] = []
        if runs_dir:
            args.extend(["--runs-dir", runs_dir])
        args.extend(["run", plan_path, "--jsonl"])
        if input_json.get("detach"):
            args.append("--detach")
        if input_json.get("embedding_surface"):
            args.extend(["--embedding", str(input_json["embedding_surface"])])
        if input_json.get("workspace_root"):
            args.extend(["--workspace-root", str(input_json["workspace_root"])])
        rc, stdout, stderr = _execute(args, _cli_env(input_json), timeout=600)
    finally:
        try:
            os.unlink(plan_path)
        except OSError:
            pass
    
    return _build_run_response(rc, stdout, stderr)


def _do_status(input_json: dict[str, Any], runs_dir: str | None) -> dict[str, Any]:
    run_id = input_json.get("run_id")
    if not run_id:
        return {"status": "error", "exit_code": 1, "message": "run_id required for status mode"}
    
    args: list[str] = []
    if runs_dir:
        args.extend(["--runs-dir", runs_dir])
    args.extend(["status", str(run_id), "--json"])
    rc, stdout, stderr = _execute(args, _cli_env(input_json), timeout=30)
    
    out: dict[str, Any] = {"exit_code": rc, "status": _exit_to_status(rc), "run_id": run_id}
    if rc == 4:
        out["message"] = f"unknown run_id: {run_id}"
        return out
    
    parsed = _parse_json(stdout)
    if parsed:
        manifest = parsed.get("manifest") or {}
        result = parsed.get("result") or {}
        out["phase"] = manifest.get("current_phase", "")
        out["current_status"] = manifest.get("current_status", "")
        out["event_count"] = parsed.get("event_count", 0)
        out["attempts"] = parsed.get("attempts", [])
        out["is_terminal"] = parsed.get("is_terminal", False)
        out["plan"] = parsed.get("plan")
        out["plan_present"] = parsed.get("plan_present", False)
        out["plan_status"] = parsed.get("plan_status", "missing")
        out["plan_path"] = parsed.get("plan_path", "")
        out["semantic_state"] = _derive_semantic_state(out["current_status"], out["attempts"])
        if result:
            out["terminal_status"] = result.get("terminal_status", "")
            out["completed_tasks"] = result.get("completed_tasks", [])
            out["failed_tasks"] = result.get("failed_tasks", [])
    elif stdout:
        out["raw_stdout"] = stdout[:500]
    if stderr:
        out["stderr"] = stderr.strip()
    return out


def _do_watch(input_json: dict[str, Any], runs_dir: str | None) -> dict[str, Any]:
    run_id = input_json.get("run_id")
    if not run_id:
        return {"status": "error", "exit_code": 1, "message": "run_id required for watch mode"}
    
    args: list[str] = []
    if runs_dir:
        args.extend(["--runs-dir", runs_dir])
    args.extend(["watch", str(run_id), "--jsonl", "--from", "0"])
    follow = input_json.get("follow", False)
    if follow:
        args.append("--follow")
        timeout_arg = int(input_json.get("follow_timeout_seconds", 600))
        args.extend(["--follow-timeout", str(timeout_arg)])
    
    timeout_seconds = int(input_json.get("follow_timeout_seconds", 30)) + 30
    rc, stdout, stderr = _execute(args, _cli_env(input_json), timeout=timeout_seconds)
    
    out: dict[str, Any] = {"exit_code": rc, "status": _exit_to_status(rc), "run_id": run_id}
    if rc == 4:
        out["message"] = f"unknown run_id: {run_id}"
        return out
    
    out["events"] = _parse_jsonl(stdout)
    try:
        from crucible.runtime.run_store import load_run_store, default_runs_root

        store = load_run_store(str(run_id), runs_root=runs_dir or default_runs_root())
        if store is not None:
            manifest = store.read_manifest()
            durable_plan = store.read_plan()
            out["plan_present"] = durable_plan is not None
            out["plan_status"] = (durable_plan or {}).get("status") or (manifest.plan_status if manifest else "missing")
            out["plan_path"] = store.plan_path
            out["plan"] = durable_plan
    except Exception:
        pass
    if stderr:
        out["stderr"] = stderr.strip()
    return out


def _do_resume(input_json: dict[str, Any], runs_dir: str | None) -> dict[str, Any]:
    run_id = input_json.get("run_id")
    if not run_id:
        return {"status": "error", "exit_code": 1, "message": "run_id required for resume mode"}

    adapter_factory = _resolve_adapter_factory(input_json)
    if adapter_factory is not None:
        from crucible.runtime.run_executor import execute_run
        from crucible.runtime.run_store import load_run_store, default_runs_root, RunLockError, _canonicalize_workspace

        store = load_run_store(str(run_id), runs_root=runs_dir or default_runs_root())
        if store is None:
            return {"status": "error", "exit_code": 4, "run_id": run_id, "message": f"unknown run_id: {run_id}"}

        manifest = store.read_manifest()
        if manifest is None:
            return {"status": "error", "exit_code": 5, "run_id": run_id, "message": f"manifest missing for run_id: {run_id}"}

        out: dict[str, Any] = {
            "run_id": run_id,
            "run_root": store.run_root,
            "workspace_root": manifest.workspace_root,
            "embedding_session_ref": manifest.embedding_session_ref,
        }

        try:
            store.acquire_lock()
        except RunLockError as e:
            out.update({"status": "error", "exit_code": 5, "message": str(e)})
            return out

        try:
            if store.is_terminal():
                result = store.read_result() or {}
                durable_plan = store.read_plan()
                out.update({
                    "status": "ok" if result.get("terminal_status") == RunTerminalStatus.SUCCEEDED.value else "terminal",
                    "exit_code": 0 if result.get("terminal_status") == RunTerminalStatus.SUCCEEDED.value else 3,
                    "terminal_status": result.get("terminal_status", ""),
                    "completed_tasks": result.get("completed_tasks", []),
                    "failed_tasks": result.get("failed_tasks", []),
                    "semantic_state": _derive_semantic_state(result.get("terminal_status", "complete")),
                    "plan_status": (durable_plan or {}).get("status", "missing"),
                    "plan_path": store.plan_path,
                    "plan": durable_plan,
                })
                return out

            flagged = store.reconcile_in_flight_attempts()
            store.append_event("run_resumed", payload={"reconciled_attempts": [a.attempt_id for a in flagged]})
            if store.read_tasks_snapshot() is None:
                out.update({"status": "error", "exit_code": 5, "message": f"run {run_id} is missing plan"})
                return out
            try:
                durable_plan = ensure_validated_plan(store.read_plan())
            except PlanningError as e:
                out.update({"status": "error", "exit_code": 5, "message": f"run {run_id} has invalid or missing durable plan.json: {e}"})
                return out

            cli_override = input_json.get("workspace_root")
            cli_override = _canonicalize_workspace(cli_override) if cli_override else ""
            if manifest.workspace_root:
                if cli_override and cli_override != manifest.workspace_root:
                    out.update({
                        "status": "error",
                        "exit_code": 1,
                        "message": (
                            f"--workspace-root {cli_override} does not match the run's persisted "
                            f"workspace_root {manifest.workspace_root}. Refusing to resume to avoid "
                            f"manifest/execution inconsistency."
                        ),
                    })
                    return out
                workspace_root = manifest.workspace_root
            else:
                raw_override = cli_override or os.environ.get("CRUCIBLE_WORKSPACE_ROOT")
                if not raw_override:
                    out.update({
                        "status": "error",
                        "exit_code": 1,
                        "message": (
                            f"run {run_id} was created without workspace_root and no --workspace-root "
                            f"override was provided. Refusing to resume in ambient cwd ({os.getcwd()})."
                        ),
                    })
                    return out
                workspace_root = _canonicalize_workspace(raw_override)
                manifest.workspace_root = workspace_root
                store.write_manifest(manifest)
                out["workspace_root"] = workspace_root

            summary = execute_run(
                store=store,
                manifest=manifest,
                plan=durable_plan,
                adapter_factory=adapter_factory,
                workspace_root=workspace_root,
            )
            out.update({
                "status": "ok" if summary.terminal_status == RunTerminalStatus.SUCCEEDED.value else "terminal",
                "exit_code": 0 if summary.terminal_status == RunTerminalStatus.SUCCEEDED.value else 3,
                "terminal_status": summary.terminal_status,
                "completed_tasks": summary.completed_tasks,
                "failed_tasks": summary.failed_tasks,
                "partial_tasks": summary.partial_tasks,
                "blocked_reason": summary.blocked_reason,
                "semantic_state": _derive_semantic_state(summary.terminal_status),
                "plan_status": durable_plan.get("status", "missing"),
                "plan_path": store.plan_path,
                "plan": durable_plan,
            })
            return out
        finally:
            store.release_lock()
    
    args: list[str] = []
    if runs_dir:
        args.extend(["--runs-dir", runs_dir])
    args.extend(["resume", str(run_id), "--jsonl"])
    if input_json.get("workspace_root"):
        args.extend(["--workspace-root", str(input_json["workspace_root"])])
    rc, stdout, stderr = _execute(args, _cli_env(input_json), timeout=600)
    
    out: dict[str, Any] = {"exit_code": rc, "status": _exit_to_status(rc), "run_id": run_id}
    if rc == 4:
        out["message"] = f"unknown run_id: {run_id}"
        return out
    if stderr.strip() and rc != 0:
        out["message"] = stderr.strip().splitlines()[-1]
    
    # Round-8 fix: the wrapper docstring promises run_root is always present
    # after resume. Look it up directly from the run store rather than hoping
    # the CLI prints it (it doesn't, by design — resume reuses the existing
    # run_root from the manifest).
    try:
        from crucible.runtime.run_store import load_run_store, default_runs_root
        store = load_run_store(run_id, runs_root=runs_dir or default_runs_root())
        if store is not None:
            out["run_root"] = store.run_root
            manifest = store.read_manifest()
            if manifest:
                out["workspace_root"] = manifest.workspace_root
                out["embedding_session_ref"] = manifest.embedding_session_ref
                out["plan_status"] = manifest.plan_status
            durable_plan = store.read_plan()
            if durable_plan is not None:
                out["plan"] = durable_plan
                out["plan_status"] = durable_plan.get("status", out.get("plan_status", "missing"))
                out["plan_path"] = store.plan_path
    except Exception:
        # Best-effort; don't break the wrapper if introspection fails
        pass
    
    parsed_lines = _parse_jsonl(stdout)
    for obj in parsed_lines:
        if obj.get("event") == "already_terminal":
            result = obj.get("result") or {}
            out["terminal_status"] = result.get("terminal_status", "")
            out["completed_tasks"] = result.get("completed_tasks", [])
            out["failed_tasks"] = result.get("failed_tasks", [])
            out["semantic_state"] = _derive_semantic_state(result.get("terminal_status", ""))
        if obj.get("event") == "resumed":
            summary = obj.get("summary") or {}
            out["terminal_status"] = summary.get("terminal_status", "")
            out["completed_tasks"] = summary.get("completed_tasks", [])
            out["failed_tasks"] = summary.get("failed_tasks", [])
            out["semantic_state"] = _derive_semantic_state(summary.get("terminal_status", ""))
            out["plan_status"] = obj.get("plan_status", out.get("plan_status", "missing"))
            out["plan_path"] = obj.get("plan_path", out.get("plan_path", ""))
    if stderr:
        out["stderr"] = stderr.strip()
    return out


def _build_run_response(rc: int, stdout: str, stderr: str) -> dict[str, Any]:
    out: dict[str, Any] = {"exit_code": rc, "status": _exit_to_status(rc)}
    parsed_lines = _parse_jsonl(stdout)
    
    for obj in parsed_lines:
        event = obj.get("event")
        if event in {"run_started", "detached", "run_pending_orchestrator"}:
            if obj.get("run_id"):
                out["run_id"] = obj["run_id"]
            if obj.get("run_root"):
                out["run_root"] = obj["run_root"]
            if obj.get("pid"):
                out["pid"] = obj["pid"]
        elif event == "plan_validated":
            out["plan_status"] = obj.get("plan_status", "")
            out["plan_path"] = obj.get("plan_path", "")
            if out.get("plan_path") and os.path.isfile(out["plan_path"]):
                try:
                    out["plan"] = json.loads(open(out["plan_path"]).read())
                except Exception:
                    pass
        elif event == "lint_failed":
            out["status"] = "lint_failed"
            out["findings"] = obj.get("result", {}).get("findings", [])
        elif event == "run_terminal":
            summary = obj.get("summary") or {}
            out["terminal_status"] = summary.get("terminal_status", "")
            out["semantic_state"] = _derive_semantic_state(summary.get("terminal_status", ""))
            out["completed_tasks"] = summary.get("completed_tasks", [])
            out["failed_tasks"] = summary.get("failed_tasks", [])
            out["partial_tasks"] = summary.get("partial_tasks", [])
            out["blocked_reason"] = summary.get("blocked_reason", "")
            out["total_runtime_seconds"] = summary.get("total_runtime_seconds", 0)
    
    # If we got nothing structured, surface raw for debugging
    if "run_id" not in out and not parsed_lines:
        out["raw_stdout"] = stdout[:500]
    if stderr:
        out["stderr"] = stderr.strip()
    return out


# ─────────────────────────────────────────────────────────────────
# Public entry
# ─────────────────────────────────────────────────────────────────

def execute(input_json: dict[str, Any]) -> dict[str, Any]:
    """Execute the crucible tool. See module docstring for the contract."""
    if not isinstance(input_json, dict):
        return {"status": "error", "exit_code": 1, "message": "input must be a dict"}
    
    mode = input_json.get("mode", "run")
    runs_dir = input_json.get("runs_dir") or os.environ.get("CRUCIBLE_RUNS_DIR")
    
    handlers = {
        "lint": _do_lint,
        "run": _do_run,
        "status": _do_status,
        "watch": _do_watch,
        "resume": _do_resume,
    }
    handler = handlers.get(mode)
    if handler is None:
        return {
            "status": "error",
            "exit_code": 1,
            "message": f"unknown mode: {mode}",
        }
    
    return handler(input_json, runs_dir)


# OpenClaw tool contract
TOOL_SCHEMA = {
    "name": TOOL_NAME,
    "description": "Run validated multi-step software builds with Crucible",
    "input_schema": {
        "type": "object",
        "properties": {
            "plan": {"type": "object", "description": "Crucible task plan"},
            "mode": {
                "type": "string",
                "enum": ["run", "lint", "status", "watch", "resume"],
                "default": "run",
            },
            "run_id": {"type": "string"},
            "detach": {"type": "boolean", "default": False},
            "embedding_surface": {"type": "string", "default": "openclaw"},
            "embedding_session_ref": {"type": "string"},
            "workspace_root": {"type": "string"},
            "runs_dir": {"type": "string"},
            "follow": {"type": "boolean", "default": False},
            "follow_timeout_seconds": {"type": "integer", "default": 30},
        },
        "required": ["mode"],
    },
}

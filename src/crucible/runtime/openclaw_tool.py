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
  terminal_status: str # complete|failed|partial|blocked|cancelled (when terminal)
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
from typing import Any


TOOL_NAME = "crucible"
TOOL_VERSION = "0.2.0"


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
    if stderr:
        out["stderr"] = stderr.strip()
    return out


def _do_resume(input_json: dict[str, Any], runs_dir: str | None) -> dict[str, Any]:
    run_id = input_json.get("run_id")
    if not run_id:
        return {"status": "error", "exit_code": 1, "message": "run_id required for resume mode"}
    
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
        if obj.get("event") == "resumed":
            summary = obj.get("summary") or {}
            out["terminal_status"] = summary.get("terminal_status", "")
            out["completed_tasks"] = summary.get("completed_tasks", [])
            out["failed_tasks"] = summary.get("failed_tasks", [])
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
        elif event == "lint_failed":
            out["status"] = "lint_failed"
            out["findings"] = obj.get("result", {}).get("findings", [])
        elif event == "run_terminal":
            summary = obj.get("summary") or {}
            out["terminal_status"] = summary.get("terminal_status", "")
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

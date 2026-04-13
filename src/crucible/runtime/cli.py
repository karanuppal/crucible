"""Phase 8 §25.3: Crucible CLI.

Commands:
  crucible run <plan-path|->     [--detach] [--jsonl] [--runs-dir DIR]
  crucible status <run_id>       [--json] [--runs-dir DIR]
  crucible watch <run_id>        [--jsonl] [--from <event_id>] [--runs-dir DIR]
  crucible resume <run_id>       [--jsonl] [--runs-dir DIR]
  crucible lint-plan <plan-path|->  [--json]

Exit codes (v5.3 §25.3):
  0  success
  1  usage error
  2  lint failure
  3  run blocked / failed / partial
  4  unknown run id
  5  internal error
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any

from crucible.planning import (
    PlanningError,
    build_plan_artifact,
    detect_ambiguity,
    ensure_validated_plan,
)
from crucible.runtime.preflight import lint_plan, LintResult
from crucible.runtime.run_store import (
    RunStore, RunSummary, create_run_store, load_run_store, default_runs_root,
)
from crucible.runtime.statuses import (
    NONSUCCESS_RUN_STATUSES,
    RunTerminalStatus,
    legacy_run_status,
)
from crucible.runtime.run_executor import execute_run


# ─────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────

def _read_plan(path_or_dash: str) -> dict[str, Any]:
    if path_or_dash == "-":
        return json.load(sys.stdin)
    with open(path_or_dash) as f:
        return json.load(f)


def _emit_jsonl(obj: dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(obj, separators=(",", ":")) + "\n")
    sys.stdout.flush()


def _emit_json(obj: dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(obj, indent=2) + "\n")
    sys.stdout.flush()


# ─────────────────────────────────────────────────────────────────
# Commands
# ─────────────────────────────────────────────────────────────────

def cmd_lint_plan(args: argparse.Namespace) -> int:
    try:
        plan = _read_plan(args.plan)
    except FileNotFoundError:
        sys.stderr.write(f"plan file not found: {args.plan}\n")
        return 1
    except json.JSONDecodeError as e:
        sys.stderr.write(f"plan is not valid JSON: {e}\n")
        return 1
    
    result = lint_plan(plan)
    
    if args.json:
        _emit_json(result.to_dict())
    else:
        if result.valid:
            print(f"OK: plan is valid ({len(result.warnings())} warnings)")
            for w in result.warnings():
                print(f"  WARN [{w.code}] {w.message}")
        else:
            print(f"FAIL: plan is invalid ({len(result.errors())} errors)")
            for e in result.errors():
                loc = f"{e.task_id}" + (f".{e.criterion_id}" if e.criterion_id else "")
                loc = f" [{loc}]" if loc.strip() else ""
                print(f"  ERROR [{e.code}]{loc} {e.message}")
            for w in result.warnings():
                loc = f"{w.task_id}" + (f".{w.criterion_id}" if w.criterion_id else "")
                loc = f" [{loc}]" if loc.strip() else ""
                print(f"  WARN  [{w.code}]{loc} {w.message}")
    
    return 0 if result.valid else 2


def cmd_run(args: argparse.Namespace) -> int:
    try:
        plan = _read_plan(args.plan)
    except FileNotFoundError:
        sys.stderr.write(f"plan file not found: {args.plan}\n")
        return 1
    except json.JSONDecodeError as e:
        sys.stderr.write(f"plan is not valid JSON: {e}\n")
        return 1
    
    # Preflight
    lint = lint_plan(plan)
    if not lint.valid:
        if args.jsonl:
            _emit_jsonl({"event": "lint_failed", "result": lint.to_dict()})
        else:
            sys.stderr.write("plan failed preflight validation:\n")
            for e in lint.errors():
                loc = f" [{e.task_id}.{e.criterion_id}]" if e.criterion_id else f" [{e.task_id}]"
                sys.stderr.write(f"  ERROR [{e.code}]{loc.strip(' []')} {e.message}\n")
        return 2
    
    normalized = lint.normalized_plan or plan
    
    # Resolve workspace_root upfront so we can persist it on the manifest
    from crucible.runtime.run_store import _canonicalize_workspace
    workspace_root = (
        args.workspace_root
        or os.environ.get("CRUCIBLE_WORKSPACE_ROOT")
        or os.getcwd()
    )
    workspace_root = _canonicalize_workspace(workspace_root)
    
    # Create run store
    runs_root = args.runs_dir or default_runs_root()
    embedding_surface = args.embedding or os.environ.get("CRUCIBLE_EMBEDDING_SURFACE", "")
    embedding_session_ref = os.environ.get("CRUCIBLE_EMBEDDING_SESSION_REF", "")
    store, manifest = create_run_store(
        run_id=None,
        project_id=normalized["project_id"],
        build_id=normalized["build_id"],
        spec_text=normalized.get("spec", ""),
        task_plan=normalized,
        embedding_surface=embedding_surface,
        embedding_session_ref=embedding_session_ref,
        runs_root=runs_root,
        workspace_root=workspace_root,
        persist_validated_plan=False,
    )

    ambiguity = detect_ambiguity(normalized)
    if ambiguity.should_escalate:
        store.append_event("run_escalated", payload={"ambiguity": ambiguity.to_dict()})
        manifest.current_phase = "planning"
        manifest.current_status = "escalated"
        store.write_manifest(manifest)
        if args.jsonl:
            _emit_jsonl({"event": "ambiguity_detected", "run_id": manifest.run_id, "ambiguity": ambiguity.to_dict()})
        else:
            print("ambiguity_detected: true")
            print(f"ambiguity_reasons: {ambiguity.reasons}")
        return 3

    try:
        durable_plan = build_plan_artifact(
            run_id=manifest.run_id,
            submitted_plan=normalized,
            embedding_surface=embedding_surface,
            embedding_session_ref=embedding_session_ref,
        )
    except PlanningError as e:
        store.append_event("plan_invalid", payload={"error": str(e)})
        manifest.current_phase = "planning"
        manifest.current_status = "failed"
        store.write_manifest(manifest)
        if args.jsonl:
            _emit_jsonl({"event": "plan_invalid", "run_id": manifest.run_id, "error": str(e)})
        else:
            sys.stderr.write(f"plan invalid: {e}\n")
        return 2

    store.write_plan(durable_plan)
    store.append_event("plan_validated", payload={"plan_ref": store.plan_path, "plan_status": durable_plan["status"]})
    manifest = store.read_manifest() or manifest
    
    if args.jsonl:
        _emit_jsonl({
            "event": "run_started",
            "run_id": manifest.run_id,
            "run_root": manifest.run_root,
        })
        _emit_jsonl({
            "event": "plan_validated",
            "run_id": manifest.run_id,
            "plan_status": durable_plan["status"],
            "plan_path": store.plan_path,
        })
    else:
        print(f"run_id: {manifest.run_id}")
        print(f"run_root: {manifest.run_root}")
    
    # Acquire write lock for foreground execution
    from crucible.runtime.run_store import RunLockError
    
    if args.detach:
        # Detached: spawn a background process running this same CLI in
        # foreground mode against the existing run dir via the resume path.
        import subprocess as _sp
        runs_root = args.runs_dir or default_runs_root()
        env = os.environ.copy()
        proc = _sp.Popen(
            [sys.executable, "-m", "crucible.runtime.cli",
             "--runs-dir", runs_root, "resume", manifest.run_id],
            stdout=_sp.DEVNULL,
            stderr=_sp.DEVNULL,
            env=env,
            start_new_session=True,
        )
        if args.jsonl:
            _emit_jsonl({
                "event": "detached",
                "run_id": manifest.run_id,
                "pid": proc.pid,
            })
        else:
            print(f"(detached pid={proc.pid})")
        return 0
    
    # Foreground: invoke orchestrator with the default local-shell adapter.
    # Embedders can override by importing execute_run() directly with their
    # own adapter factory (e.g. one backed by SessionsSpawnBridge).
    from crucible.runtime.local_shell_adapter import LocalShellAdapter
    
    def _default_factory(s: RunStore):
        return [LocalShellAdapter()]
    
    try:
        store.acquire_lock()
    except RunLockError as e:
        sys.stderr.write(f"{e}\n")
        return 5
    
    try:
        ensure_validated_plan(store.read_plan())
        summary = execute_run(
            store=store,
            manifest=manifest,
            plan=ensure_validated_plan(store.read_plan()),
            adapter_factory=_default_factory,
            workspace_root=workspace_root,
        )
    finally:
        store.release_lock()
    
    if args.jsonl:
        _emit_jsonl({"event": "run_terminal", "summary": summary.to_dict()})
    else:
        print(f"terminal_status: {summary.terminal_status}")
        print(f"completed: {summary.completed_tasks}")
        print(f"failed: {summary.failed_tasks}")
    
    if summary.terminal_status == RunTerminalStatus.SUCCEEDED.value:
        return 0
    return 3


def cmd_status(args: argparse.Namespace) -> int:
    runs_root = args.runs_dir or default_runs_root()
    store = load_run_store(args.run_id, runs_root=runs_root)
    if store is None:
        sys.stderr.write(f"unknown run_id: {args.run_id}\n")
        return 4
    
    manifest = store.read_manifest()
    result = store.read_result()
    events = store.read_events()
    attempts = store.list_attempts()
    durable_plan = store.read_plan()
    
    snapshot = {
        "manifest": manifest.to_dict() if manifest else None,
        "result": result,
        "plan": durable_plan,
        "plan_present": durable_plan is not None,
        "plan_status": (durable_plan or {}).get("status") or (manifest.plan_status if manifest else "missing"),
        "plan_path": store.plan_path,
        "event_count": len(events),
        "last_events": [e.to_dict() for e in events[-5:]],
        "attempts": [a.to_dict() for a in attempts],
        "is_terminal": store.is_terminal(),
    }
    
    if args.json:
        _emit_json(snapshot)
    else:
        if manifest:
            print(f"run_id: {manifest.run_id}")
            print(f"phase: {manifest.current_phase}")
            print(f"status: {manifest.current_status}")
            print(f"events: {len(events)}")
            print(f"attempts: {len(attempts)}")
            print(f"plan_present: {durable_plan is not None}")
            print(f"plan_status: {(durable_plan or {}).get('status') or manifest.plan_status}")
            print(f"plan_path: {store.plan_path}")
            if result:
                print(f"terminal_status: {result.get('terminal_status')}")
                print(f"completed: {result.get('completed_tasks')}")
                print(f"failed: {result.get('failed_tasks')}")
        else:
            print("(no manifest yet)")
    
    if result:
        ts = result.get("terminal_status")
        if ts == RunTerminalStatus.SUCCEEDED.value:
            return 0
        if ts in NONSUCCESS_RUN_STATUSES or ts == "partial":
            return 3
    return 0


def cmd_watch(args: argparse.Namespace) -> int:
    import time as _time
    runs_root = args.runs_dir or default_runs_root()
    store = load_run_store(args.run_id, runs_root=runs_root)
    if store is None:
        sys.stderr.write(f"unknown run_id: {args.run_id}\n")
        return 4

    manifest = store.read_manifest()
    durable_plan = store.read_plan()
    plan_snapshot = {
        "event": "plan_state",
        "run_id": args.run_id,
        "plan_present": durable_plan is not None,
        "plan_status": (durable_plan or {}).get("status") or (manifest.plan_status if manifest else "missing"),
        "plan_path": store.plan_path,
        "plan": durable_plan,
    }
    
    def _emit_events(events):
        if args.jsonl:
            for e in events:
                _emit_jsonl(e.to_dict())
        else:
            for e in events:
                loc = f"[{e.task_id}]" if e.task_id else ""
                print(f"{e.timestamp:.0f} {e.type:30s} {loc} {json.dumps(e.payload)}")
    
    if args.jsonl:
        _emit_jsonl(plan_snapshot)
    else:
        print(f"plan_present: {plan_snapshot['plan_present']}")
        print(f"plan_status: {plan_snapshot['plan_status']}")
        print(f"plan_path: {plan_snapshot['plan_path']}")

    seen_event_ids: set[str] = set()
    initial = store.read_events(from_event_id=args.from_event)
    for e in initial:
        seen_event_ids.add(e.event_id)
    _emit_events(initial)
    
    if args.follow and not store.is_terminal():
        deadline = _time.time() + max(1, args.follow_timeout)
        while _time.time() < deadline:
            _time.sleep(min(0.25, max(0.0, deadline - _time.time())))
            new_events = []
            for e in store.read_events():
                if e.event_id not in seen_event_ids:
                    new_events.append(e)
                    seen_event_ids.add(e.event_id)
            if new_events:
                _emit_events(new_events)
            if store.is_terminal():
                break
    
    if store.is_terminal():
        result = store.read_result()
        ts = result.get("terminal_status") if result else None
        if ts == RunTerminalStatus.SUCCEEDED.value:
            return 0
        if ts in NONSUCCESS_RUN_STATUSES or ts == "partial":
            return 3
    return 0


def cmd_resume(args: argparse.Namespace) -> int:
    from crucible.runtime.run_store import RunLockError
    runs_root = args.runs_dir or default_runs_root()
    store = load_run_store(args.run_id, runs_root=runs_root)
    if store is None:
        sys.stderr.write(f"unknown run_id: {args.run_id}\n")
        return 4
    
    # Acquire write lock — fails if another resume is already in flight.
    try:
        store.acquire_lock()
    except RunLockError as e:
        sys.stderr.write(f"{e}\n")
        if args.jsonl:
            _emit_jsonl({"event": "lock_busy", "run_id": args.run_id})
        return 5
    
    if store.is_terminal():
        result = store.read_result()
        store.release_lock()
        if args.jsonl:
            _emit_jsonl({"event": "already_terminal", "result": result})
        else:
            print(f"already terminal: {result.get('terminal_status') if result else 'unknown'}")
        return 0 if result and result.get("terminal_status") == RunTerminalStatus.SUCCEEDED.value else 3
    
    # Reconcile in-flight attempts and re-execute the plan from the
    # persisted snapshot. The executor is idempotent enough for our
    # current sync model: completed criteria stay completed; failed/missing
    # criteria are re-attempted.
    flagged = store.reconcile_in_flight_attempts()
    store.append_event("run_resumed", payload={"reconciled_attempts": [a.attempt_id for a in flagged]})
    
    manifest = store.read_manifest()
    if store.read_tasks_snapshot() is None or manifest is None:
        sys.stderr.write(f"run {args.run_id} is missing plan or manifest\n")
        store.release_lock()
        return 5
    try:
        durable_plan = ensure_validated_plan(store.read_plan())
    except PlanningError as e:
        sys.stderr.write(f"run {args.run_id} has invalid or missing durable plan.json: {e}\n")
        store.release_lock()
        return 5
    
    from crucible.runtime.local_shell_adapter import LocalShellAdapter
    
    def _factory(s: RunStore):
        return [LocalShellAdapter()]
    
    # Restore workspace_root from manifest. Round-4 fix: refuse to silently
    # fall back to cwd if the manifest doesn't have one (e.g. older runs
    # created before workspace_root was persisted). The user must pass
    # --workspace-root on resume, or set CRUCIBLE_WORKSPACE_ROOT env var.
    #
    # Round-5 fix: if manifest already has workspace_root, refuse any
    # --workspace-root override that doesn't match. Otherwise the run
    # record (manifest says A) becomes inconsistent with execution
    # (events show work happened in B).
    from crucible.runtime.run_store import _canonicalize_workspace
    cli_override = getattr(args, "workspace_root", None)
    if cli_override:
        cli_override = _canonicalize_workspace(cli_override)
    
    if manifest.workspace_root:
        # Manifest already pinned a workspace. Override must match (or be absent).
        if cli_override and cli_override != manifest.workspace_root:
            sys.stderr.write(
                f"--workspace-root {cli_override} does not match the run's "
                f"persisted workspace_root {manifest.workspace_root}. "
                f"Refusing to resume to avoid manifest/execution inconsistency.\n"
            )
            store.release_lock()
            return 1
        workspace_root = manifest.workspace_root
    else:
        # No manifest pin → require explicit override (round-4 rule)
        env_override = os.environ.get("CRUCIBLE_WORKSPACE_ROOT")
        raw_override = cli_override or env_override
        if not raw_override:
            sys.stderr.write(
                f"run {args.run_id} was created without workspace_root and no "
                f"--workspace-root override was provided. Refusing to resume in "
                f"ambient cwd ({os.getcwd()}). Pass --workspace-root explicitly.\n"
            )
            store.release_lock()
            return 1
        # Round-7 fix: canonicalize via the SAME helper as everywhere else
        # so the manifest, the executor, and the events all see the
        # identical path string (no symlink-vs-realpath drift).
        workspace_root = _canonicalize_workspace(raw_override)
        manifest.workspace_root = workspace_root
        store.write_manifest(manifest)
    
    try:
        summary = execute_run(
            store=store,
            manifest=manifest,
            plan=durable_plan,
            adapter_factory=_factory,
            workspace_root=workspace_root,
        )
    finally:
        store.release_lock()
    
    if args.jsonl:
        _emit_jsonl({
            "event": "resumed",
            "run_id": args.run_id,
            "reconciled": [a.attempt_id for a in flagged],
            "plan_status": durable_plan.get("status", "missing"),
            "plan_path": store.plan_path,
            "summary": summary.to_dict(),
        })
    else:
        print(f"resumed run {args.run_id}")
        print(f"reconciled {len(flagged)} in-flight attempts")
        print(f"plan_status: {durable_plan.get('status', 'missing')}")
        print(f"plan_path: {store.plan_path}")
        print(f"terminal_status: {summary.terminal_status}")
    
    return 0 if summary.terminal_status == RunTerminalStatus.SUCCEEDED.value else 3


# ─────────────────────────────────────────────────────────────────
# Entry
# ─────────────────────────────────────────────────────────────────

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="crucible", description="Crucible harness CLI")
    parser.add_argument("--runs-dir", default=None, help="override runs/ root")
    sub = parser.add_subparsers(dest="command", required=True)
    
    p_lint = sub.add_parser("lint-plan", help="preflight-validate a task plan")
    p_lint.add_argument("plan", help="path to plan JSON or '-' for stdin")
    p_lint.add_argument("--json", action="store_true")
    p_lint.set_defaults(func=cmd_lint_plan)
    
    p_run = sub.add_parser("run", help="start a new Crucible run")
    p_run.add_argument("plan", help="path to plan JSON or '-' for stdin")
    p_run.add_argument("--detach", action="store_true", help="background execution")
    p_run.add_argument("--jsonl", action="store_true", help="JSONL event output")
    p_run.add_argument("--embedding", default="", help="embedding surface name (e.g. openclaw)")
    p_run.add_argument("--workspace-root", default=None, help="directory verification commands run in")
    p_run.set_defaults(func=cmd_run)
    
    p_status = sub.add_parser("status", help="snapshot a run's state")
    p_status.add_argument("run_id")
    p_status.add_argument("--json", action="store_true")
    p_status.set_defaults(func=cmd_status)
    
    p_watch = sub.add_parser("watch", help="stream a run's events")
    p_watch.add_argument("run_id")
    p_watch.add_argument("--jsonl", action="store_true")
    p_watch.add_argument("--from", dest="from_event", default=None)
    p_watch.add_argument("--follow", action="store_true", help="poll for new events until terminal")
    p_watch.add_argument("--follow-timeout", type=int, default=600, dest="follow_timeout")
    p_watch.set_defaults(func=cmd_watch)
    
    p_resume = sub.add_parser("resume", help="re-enter an interrupted run")
    p_resume.add_argument("run_id")
    p_resume.add_argument("--jsonl", action="store_true")
    p_resume.add_argument("--workspace-root", default=None,
                          help="override workspace_root (required if manifest doesn't have one)")
    p_resume.set_defaults(func=cmd_resume)
    
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except Exception as e:
        sys.stderr.write(f"internal error: {e}\n")
        import traceback
        traceback.print_exc()
        return 5


if __name__ == "__main__":
    sys.exit(main())

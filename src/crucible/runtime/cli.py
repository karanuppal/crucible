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

from crucible.runtime.preflight import lint_plan, LintResult
from crucible.runtime.run_store import (
    RunStore, RunSummary, create_run_store, load_run_store, default_runs_root,
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
    
    # Create run store
    runs_root = args.runs_dir or default_runs_root()
    store, manifest = create_run_store(
        run_id=None,
        project_id=normalized["project_id"],
        build_id=normalized["build_id"],
        spec_text=normalized.get("spec", ""),
        task_plan=normalized,
        embedding_surface=args.embedding or "",
        runs_root=runs_root,
    )
    
    if args.jsonl:
        _emit_jsonl({
            "event": "run_started",
            "run_id": manifest.run_id,
            "run_root": manifest.run_root,
        })
    else:
        print(f"run_id: {manifest.run_id}")
        print(f"run_root: {manifest.run_root}")
    
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
    
    summary = execute_run(
        store=store,
        manifest=manifest,
        plan=normalized,
        adapter_factory=_default_factory,
    )
    
    if args.jsonl:
        _emit_jsonl({"event": "run_terminal", "summary": summary.to_dict()})
    else:
        print(f"terminal_status: {summary.terminal_status}")
        print(f"completed: {summary.completed_tasks}")
        print(f"failed: {summary.failed_tasks}")
    
    if summary.terminal_status == "complete":
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
    
    snapshot = {
        "manifest": manifest.to_dict() if manifest else None,
        "result": result,
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
            if result:
                print(f"terminal_status: {result.get('terminal_status')}")
                print(f"completed: {result.get('completed_tasks')}")
                print(f"failed: {result.get('failed_tasks')}")
        else:
            print("(no manifest yet)")
    
    if result:
        ts = result.get("terminal_status")
        if ts == "complete":
            return 0
        if ts in {"blocked", "failed", "partial", "cancelled"}:
            return 3
    return 0


def cmd_watch(args: argparse.Namespace) -> int:
    runs_root = args.runs_dir or default_runs_root()
    store = load_run_store(args.run_id, runs_root=runs_root)
    if store is None:
        sys.stderr.write(f"unknown run_id: {args.run_id}\n")
        return 4
    
    events = store.read_events(from_event_id=args.from_event)
    
    if args.jsonl:
        for e in events:
            _emit_jsonl(e.to_dict())
    else:
        for e in events:
            loc = f"[{e.task_id}]" if e.task_id else ""
            print(f"{e.timestamp:.0f} {e.type:30s} {loc} {json.dumps(e.payload)}")
    
    if store.is_terminal():
        result = store.read_result()
        ts = result.get("terminal_status") if result else None
        if ts == "complete":
            return 0
        if ts in {"blocked", "failed", "partial", "cancelled"}:
            return 3
    return 0


def cmd_resume(args: argparse.Namespace) -> int:
    runs_root = args.runs_dir or default_runs_root()
    store = load_run_store(args.run_id, runs_root=runs_root)
    if store is None:
        sys.stderr.write(f"unknown run_id: {args.run_id}\n")
        return 4
    
    if store.is_terminal():
        result = store.read_result()
        if args.jsonl:
            _emit_jsonl({"event": "already_terminal", "result": result})
        else:
            print(f"already terminal: {result.get('terminal_status') if result else 'unknown'}")
        return 0 if result and result.get("terminal_status") == "complete" else 3
    
    # Reconcile in-flight attempts and re-execute the plan from the
    # persisted snapshot. The executor is idempotent enough for our
    # current sync model: completed criteria stay completed; failed/missing
    # criteria are re-attempted.
    flagged = store.reconcile_in_flight_attempts()
    store.append_event("run_resumed", payload={"reconciled_attempts": [a.attempt_id for a in flagged]})
    
    plan = store.read_tasks_snapshot()
    manifest = store.read_manifest()
    if plan is None or manifest is None:
        sys.stderr.write(f"run {args.run_id} is missing plan or manifest\n")
        return 5
    
    from crucible.runtime.local_shell_adapter import LocalShellAdapter
    
    def _factory(s: RunStore):
        return [LocalShellAdapter()]
    
    summary = execute_run(
        store=store,
        manifest=manifest,
        plan=plan,
        adapter_factory=_factory,
    )
    
    if args.jsonl:
        _emit_jsonl({
            "event": "resumed",
            "run_id": args.run_id,
            "reconciled": [a.attempt_id for a in flagged],
            "summary": summary.to_dict(),
        })
    else:
        print(f"resumed run {args.run_id}")
        print(f"reconciled {len(flagged)} in-flight attempts")
        print(f"terminal_status: {summary.terminal_status}")
    
    return 0 if summary.terminal_status == "complete" else 3


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
    p_run.set_defaults(func=cmd_run)
    
    p_status = sub.add_parser("status", help="snapshot a run's state")
    p_status.add_argument("run_id")
    p_status.add_argument("--json", action="store_true")
    p_status.set_defaults(func=cmd_status)
    
    p_watch = sub.add_parser("watch", help="stream a run's events")
    p_watch.add_argument("run_id")
    p_watch.add_argument("--jsonl", action="store_true")
    p_watch.add_argument("--from", dest="from_event", default=None)
    p_watch.set_defaults(func=cmd_watch)
    
    p_resume = sub.add_parser("resume", help="re-enter an interrupted run")
    p_resume.add_argument("run_id")
    p_resume.add_argument("--jsonl", action="store_true")
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

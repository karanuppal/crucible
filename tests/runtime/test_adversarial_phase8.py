"""G6: Adversarial test pack — every known foot-gun must have a test.

These tests are intentionally pessimistic. If the harness can survive
this list, it can survive a real OpenClaw user.
"""

import json
import os
import subprocess
import sys
import time
import pytest

from crucible.accelerators.adapters import AdapterRunSpec, AdapterStatus, AdapterRunHandle
from crucible.accelerators.capabilities import Capability
from crucible.runtime.local_shell_adapter import LocalShellAdapter
from crucible.runtime.openclaw_adapter import OpenClawSubagentAdapter
from crucible.runtime.openclaw_bridge import SimulatedOpenClawBridge
from crucible.runtime.preflight import lint_plan
from crucible.runtime.run_executor import execute_run
from crucible.runtime.run_store import create_run_store, load_run_store


CLI = [sys.executable, "-m", "crucible.runtime.cli"]


def _run(args, timeout=30):
    return subprocess.run(CLI + args, capture_output=True, text=True, timeout=timeout)


def _store(tmp_path, plan):
    normalized = lint_plan(plan).normalized_plan or plan
    return create_run_store(
        run_id=None, project_id=normalized["project_id"], build_id=normalized["build_id"],
        spec_text=normalized.get("spec", ""), task_plan=normalized,
        runs_root=str(tmp_path / "runs"),
    )


# ─────────────────────────────────────────────────────────────────
# Bad-plan ingestion
# ─────────────────────────────────────────────────────────────────

class TestBadPlanIngestion:
    def test_malformed_json_rejected(self, tmp_path):
        path = tmp_path / "bad.json"
        path.write_text("{this is not valid json")
        r = _run(["lint-plan", str(path)])
        assert r.returncode == 1
        assert "JSON" in r.stderr or "json" in r.stderr.lower()
    
    def test_empty_plan_rejected(self, tmp_path):
        path = tmp_path / "empty.json"
        path.write_text(json.dumps({"spec": "x", "project_id": "p", "build_id": "b", "tasks": []}))
        r = _run(["lint-plan", str(path)])
        assert r.returncode == 2
    
    def test_vague_description_rejected(self, tmp_path):
        plan = {
            "spec": "x", "project_id": "p", "build_id": "b",
            "tasks": [{
                "task_id": "t1",
                "description": "make it work properly",
                "criteria": [{
                    "criterion_id": "c1",
                    "criterion_class": "must_pass",
                    "triple": {
                        "build_target": "src/foo.py",
                        "verification_command": "true",
                        "expected_output": "PASSED",
                    },
                }],
                "role": "builder",
                "intensity_hint": "S",
            }],
        }
        path = tmp_path / "vague.json"
        path.write_text(json.dumps(plan))
        r = _run(["lint-plan", str(path)])
        assert r.returncode == 2
    
    def test_no_must_pass_rejected(self, tmp_path):
        plan = {
            "spec": "x", "project_id": "p", "build_id": "b",
            "tasks": [{
                "task_id": "t1",
                "description": "implement src/foo.py with tests/test_foo.py",
                "criteria": [{
                    "criterion_id": "c1",
                    "criterion_class": "informational",
                    "triple": {
                        "build_target": "src/foo.py",
                        "verification_command": "true",
                        "expected_output": "PASSED",
                    },
                }],
                "role": "builder",
                "intensity_hint": "S",
            }],
        }
        path = tmp_path / "noinit.json"
        path.write_text(json.dumps(plan))
        r = _run(["lint-plan", str(path)])
        assert r.returncode == 2


# ─────────────────────────────────────────────────────────────────
# Adapter crash + spawn failure
# ─────────────────────────────────────────────────────────────────

class _CrashingFactoryAdapter:
    def backend_id(self): return "crash"
    def declared_capabilities(self):
        from crucible.accelerators.capabilities import BackendCapabilities, Capability
        return BackendCapabilities(
            backend_id="crash",
            supports={Capability.SHELL_EXEC},
            max_concurrent_runs=1,
        )
    def spawn(self, spec):
        raise RuntimeError("backend exploded")
    def poll(self, h):
        return AdapterStatus.FAILED
    def collect(self, h):
        from crucible.accelerators.adapters import AdapterRunResult
        return AdapterRunResult(handle_id="x", status=AdapterStatus.FAILED, error="x")
    def kill(self, h): pass


class TestAdapterFailureModes:
    def test_factory_exception_marks_run_failed(self, tmp_path):
        plan = {
            "spec": "x", "project_id": "p", "build_id": "b",
            "tasks": [{
                "task_id": "t1",
                "description": "implement src/foo.py with tests/test_foo.py",
                "criteria": [{"criterion_id": "c1", "criterion_class": "must_pass",
                              "triple": {"build_target": "src/foo.py",
                                         "verification_command": "true",
                                         "expected_output": "OK_OK"}}],
                "role": "builder", "intensity_hint": "S",
            }],
        }
        store, manifest = _store(tmp_path, plan)
        
        def boom(s):
            raise RuntimeError("factory exploded")
        
        summary = execute_run(store=store, manifest=manifest, plan=plan, adapter_factory=boom)
        assert summary.terminal_status == "run_failed"
        assert "factory exploded" in summary.blocked_reason
    
    def test_no_backends_blocks_run(self, tmp_path):
        plan = {
            "spec": "x", "project_id": "p", "build_id": "b",
            "tasks": [{
                "task_id": "t1",
                "description": "implement src/foo.py with tests/test_foo.py",
                "criteria": [{"criterion_id": "c1", "criterion_class": "must_pass",
                              "triple": {"build_target": "src/foo.py",
                                         "verification_command": "true",
                                         "expected_output": "OK_OK"}}],
                "role": "builder", "intensity_hint": "S",
            }],
        }
        store, manifest = _store(tmp_path, plan)
        summary = execute_run(store=store, manifest=manifest, plan=plan, adapter_factory=lambda s: [])
        assert summary.terminal_status == "run_blocked"
    
    def test_spawn_exception_marks_criterion_failed(self, tmp_path):
        plan = {
            "spec": "x", "project_id": "p", "build_id": "b",
            "tasks": [{
                "task_id": "t1",
                "description": "implement src/foo.py with tests/test_foo.py",
                "criteria": [{"criterion_id": "c1", "criterion_class": "must_pass",
                              "triple": {"build_target": "src/foo.py",
                                         "verification_command": "true",
                                         "expected_output": "OK_OK"}}],
                "role": "builder", "intensity_hint": "S",
            }],
        }
        store, manifest = _store(tmp_path, plan)
        summary = execute_run(
            store=store, manifest=manifest, plan=plan,
            adapter_factory=lambda s: [_CrashingFactoryAdapter()],
        )
        assert summary.terminal_status == "run_failed"


# ─────────────────────────────────────────────────────────────────
# Idempotency + concurrency
# ─────────────────────────────────────────────────────────────────

class TestIdempotency:
    def test_concurrent_terminal_event_for_same_handle(self, tmp_path):
        store, _ = _store(tmp_path, {
            "spec": "x", "project_id": "p", "build_id": "b",
            "tasks": [{
                "task_id": "t1",
                "description": "implement src/foo.py with tests/test_foo.py",
                "criteria": [{"criterion_id": "c1", "criterion_class": "must_pass",
                              "triple": {"build_target": "src/foo.py",
                                         "verification_command": "true",
                                         "expected_output": "OK_OK"}}],
                "role": "builder", "intensity_hint": "S",
            }],
        })
        
        adapter = OpenClawSubagentAdapter(store, spawn_fn=lambda s: f"sess-{s.spec_id}")
        spec = AdapterRunSpec(
            spec_id="t1.c1", prompt="x", cwd="/tmp", timeout_seconds=10,
            required_capabilities={Capability.SHELL_EXEC, Capability.ARTIFACT_PRODUCTION},
        )
        handle = adapter.spawn(spec)
        
        # Three terminal events for the same handle
        adapter.ingest_event(handle.handle_id, status=AdapterStatus.COMPLETE, summary="first")
        adapter.ingest_event(handle.handle_id, status=AdapterStatus.COMPLETE, summary="second")
        adapter.ingest_event(handle.handle_id, status=AdapterStatus.COMPLETE, summary="third")
        
        result = adapter.collect(handle)
        assert result.status == AdapterStatus.COMPLETE


# ─────────────────────────────────────────────────────────────────
# Restart-then-resume
# ─────────────────────────────────────────────────────────────────

class TestRestartResume:
    def test_in_flight_attempt_flagged_after_restart(self, tmp_path):
        store, _ = _store(tmp_path, {
            "spec": "x", "project_id": "p", "build_id": "b",
            "tasks": [{
                "task_id": "t1",
                "description": "implement src/foo.py with tests/test_foo.py",
                "criteria": [{"criterion_id": "c1", "criterion_class": "must_pass",
                              "triple": {"build_target": "src/foo.py",
                                         "verification_command": "true",
                                         "expected_output": "OK_OK"}}],
                "role": "builder", "intensity_hint": "S",
            }],
        })
        from crucible.runtime.run_store import TaskAttemptRecord
        store.write_attempt(TaskAttemptRecord(
            attempt_id="t1-attempt-0", task_id="t1", attempt_index=0,
            backend_id="local-shell", status="running",
        ))
        
        # Simulate restart: load fresh store
        loaded = load_run_store(store.read_manifest().run_id, runs_root=os.path.dirname(store.run_root))
        flagged = loaded.reconcile_in_flight_attempts()
        assert len(flagged) == 1
        assert flagged[0].needs_reconciliation


# ─────────────────────────────────────────────────────────────────
# Unknown run_id
# ─────────────────────────────────────────────────────────────────

class TestUnknownRunId:
    def test_status_unknown_returns_four(self, tmp_path):
        r = _run(["--runs-dir", str(tmp_path / "runs"), "status", "ghost"])
        assert r.returncode == 4
    
    def test_watch_unknown_returns_four(self, tmp_path):
        r = _run(["--runs-dir", str(tmp_path / "runs"), "watch", "ghost"])
        assert r.returncode == 4
    
    def test_resume_unknown_returns_four(self, tmp_path):
        r = _run(["--runs-dir", str(tmp_path / "runs"), "resume", "ghost"])
        assert r.returncode == 4

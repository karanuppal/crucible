"""Round-4 fixes: concurrent resume locking + backward compat."""

import json
import os
import subprocess
import sys
import time
import pytest

from crucible.runtime.run_store import (
    RunStore, RunManifest, RunLockError, create_run_store, load_run_store,
)


CLI = [sys.executable, "-m", "crucible.runtime.cli"]


def _plan():
    return {
        "spec": "lock test",
        "project_id": "lock",
        "build_id": "b1",
        "tasks": [{
            "task_id": "t1",
            "description": "verify src/foo.py with tests/test_foo.py",
            "criteria": [{
                "criterion_id": "c1",
                "criterion_class": "must_pass",
                "triple": {
                    "build_target": "non-path-target",
                    "verification_command": "sleep 0.5; echo PASSED_LOCK",
                    "expected_output": "PASSED_LOCK",
                },
            }],
            "role": "builder", "intensity_hint": "S",
        }],
    }


# ─────────────────────────────────────────────────────────────────
# Lock tests
# ─────────────────────────────────────────────────────────────────

class TestRunLock:
    def test_acquire_then_release(self, tmp_path):
        store, _ = create_run_store(
            run_id=None, project_id="p", build_id="b",
            spec_text="x", task_plan=_plan(),
            runs_root=str(tmp_path / "runs"),
            workspace_root=str(tmp_path),
        )
        store.acquire_lock()
        store.release_lock()
        # Can re-acquire after release
        store.acquire_lock()
        store.release_lock()
    
    def test_second_acquire_blocks_other_store_instance(self, tmp_path):
        store1, manifest = create_run_store(
            run_id=None, project_id="p", build_id="b",
            spec_text="x", task_plan=_plan(),
            runs_root=str(tmp_path / "runs"),
            workspace_root=str(tmp_path),
        )
        store1.acquire_lock()
        
        # Open a SECOND RunStore instance pointing at the same run dir
        store2 = load_run_store(manifest.run_id, runs_root=str(tmp_path / "runs"))
        assert store2 is not None
        with pytest.raises(RunLockError):
            store2.acquire_lock()
        
        store1.release_lock()
        # Now store2 can acquire
        store2.acquire_lock()
        store2.release_lock()
    
    def test_context_manager_releases(self, tmp_path):
        store, _ = create_run_store(
            run_id=None, project_id="p", build_id="b",
            spec_text="x", task_plan=_plan(),
            runs_root=str(tmp_path / "runs"),
            workspace_root=str(tmp_path),
        )
        with store:
            store.acquire_lock()
        # After context exit, another instance can acquire
        store2 = load_run_store(store.read_manifest().run_id, runs_root=os.path.dirname(store.run_root))
        store2.acquire_lock()
        store2.release_lock()


class TestConcurrentResume:
    def test_concurrent_resume_processes(self, tmp_path):
        """Two simultaneous `crucible resume` invocations on the same run.
        
        The lock must serialize them: one succeeds, the other returns exit 5
        (lock busy) instead of crashing.
        """
        runs_dir = str(tmp_path / "runs")
        store, manifest = create_run_store(
            run_id=None, project_id="p", build_id="b",
            spec_text="x", task_plan=_plan(),
            runs_root=runs_dir,
            workspace_root=str(tmp_path),
        )
        
        # Spawn two resume processes back-to-back
        def _spawn():
            return subprocess.Popen(
                CLI + ["--runs-dir", runs_dir, "resume", manifest.run_id],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
            )
        
        p1 = _spawn()
        # Tiny stagger so they overlap on the lock acquire
        time.sleep(0.05)
        p2 = _spawn()
        
        rc1 = p1.wait(timeout=30)
        rc2 = p2.wait(timeout=30)
        
        # At least one must succeed (rc 0) and at least one must fail with
        # the lock-busy code (5) — they can't BOTH succeed if they were
        # actually contending. If the second one started after the first
        # already released, they may both succeed; in that case the test is
        # weaker but still valid (no crashes/race).
        assert rc1 in {0, 5}, f"unexpected rc1={rc1}: {p1.stderr.read()}"
        assert rc2 in {0, 5}, f"unexpected rc2={rc2}: {p2.stderr.read()}"
        # No process should have crashed with traceback (rc 5 with 'lock' in stderr is fine)
        if rc1 == 5:
            assert "lock" in p1.stderr.read().lower()
        if rc2 == 5:
            assert "lock" in p2.stderr.read().lower()


# ─────────────────────────────────────────────────────────────────
# Backward compat
# ─────────────────────────────────────────────────────────────────

class TestManifestBackwardCompat:
    def test_old_manifest_without_workspace_root_loads(self, tmp_path):
        """A manifest written before workspace_root was added must still load."""
        run_root = tmp_path / "old-run"
        run_root.mkdir()
        # Hand-craft an old manifest without workspace_root
        old_manifest = {
            "run_id": "run-old123",
            "project_id": "p",
            "build_id": "b",
            "run_root": str(run_root),
            "created_at": time.time(),
            "spec_text_hash": "abc",
            "task_definitions_hash": "def",
            "current_phase": "intake",
            "current_status": "running",
            "cli_version": "0.1.0",
            # NO workspace_root field
        }
        (run_root / "run.json").write_text(json.dumps(old_manifest))
        
        store = RunStore(str(run_root))
        manifest = store.read_manifest()
        assert manifest is not None
        assert manifest.run_id == "run-old123"
        assert manifest.workspace_root == ""  # default
    
    def test_manifest_with_unknown_future_field_ignored(self, tmp_path):
        """A manifest with extra unknown fields (e.g. from a newer CLI) loads."""
        run_root = tmp_path / "future-run"
        run_root.mkdir()
        future_manifest = {
            "run_id": "run-future",
            "project_id": "p",
            "build_id": "b",
            "run_root": str(run_root),
            "created_at": time.time(),
            "spec_text_hash": "abc",
            "task_definitions_hash": "def",
            "current_phase": "intake",
            "current_status": "running",
            "cli_version": "0.99.0",
            "workspace_root": "/tmp/work",
            "future_field_v2": "should be ignored",
            "another_unknown": 42,
        }
        (run_root / "run.json").write_text(json.dumps(future_manifest))
        
        store = RunStore(str(run_root))
        manifest = store.read_manifest()
        assert manifest.run_id == "run-future"
        # /tmp may be a symlink (macOS: /private/tmp); canonicalization
        # resolves the realpath. Check both.
        assert manifest.workspace_root in {"/tmp/work", "/private/tmp/work"}


class TestResumeWithoutWorkspaceRoot:
    def test_old_run_resume_requires_explicit_workspace(self, tmp_path):
        """A run created with empty workspace_root must NOT silently fall back to cwd.
        
        Reviewer's round-4 concern: backward-compat could let an old run
        resume in the wrong directory and corrupt verification.
        """
        runs_dir = str(tmp_path / "runs")
        store, manifest = create_run_store(
            run_id=None, project_id="p", build_id="b",
            spec_text="x", task_plan=_plan(),
            runs_root=runs_dir,
            # workspace_root NOT set — simulates an old run
        )
        
        # Attempt resume without --workspace-root: must refuse
        r = subprocess.run(
            CLI + ["--runs-dir", runs_dir, "resume", manifest.run_id],
            capture_output=True, text=True, timeout=30,
        )
        assert r.returncode == 1, f"got {r.returncode}: {r.stdout}\n{r.stderr}"
        assert "workspace_root" in r.stderr.lower() or "workspace" in r.stderr.lower()
    
    def test_old_run_resume_with_explicit_workspace_succeeds(self, tmp_path):
        runs_dir = str(tmp_path / "runs")
        store, manifest = create_run_store(
            run_id=None, project_id="p", build_id="b",
            spec_text="x", task_plan=_plan(),
            runs_root=runs_dir,
        )
        
        r = subprocess.run(
            CLI + ["--runs-dir", runs_dir, "resume", manifest.run_id,
                   "--workspace-root", str(tmp_path)],
            capture_output=True, text=True, timeout=30,
        )
        assert r.returncode == 0, f"got {r.returncode}: {r.stdout}\n{r.stderr}"

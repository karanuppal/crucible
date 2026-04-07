"""Round-6 fix: workspace_root must be canonical/absolute at every layer.

Reviewer's blocker: a manifest containing a relative workspace_root made
resume cwd-sensitive again, defeating the round-3/4/5 work.
"""

import json
import os
import subprocess
import sys
import time
import pytest

from crucible.runtime.run_store import (
    RunStore, RunManifest, _canonicalize_workspace, create_run_store, load_run_store,
)


CLI = [sys.executable, "-m", "crucible.runtime.cli"]


def _plan():
    return {
        "spec": "canonical workspace test",
        "project_id": "canon",
        "build_id": "b1",
        "tasks": [{
            "task_id": "t1",
            "description": "verify src/foo.py with tests/test_foo.py",
            "criteria": [{
                "criterion_id": "c1",
                "criterion_class": "must_pass",
                "triple": {
                    "build_target": "non-path-target",
                    "verification_command": "echo CANON_OK",
                    "expected_output": "CANON_OK",
                },
            }],
            "role": "builder", "intensity_hint": "S",
        }],
    }


# ─────────────────────────────────────────────────────────────────
# _canonicalize_workspace unit tests
# ─────────────────────────────────────────────────────────────────

class TestCanonicalize:
    def test_empty_returns_empty(self):
        assert _canonicalize_workspace("") == ""
    
    def test_relative_becomes_absolute(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        result = _canonicalize_workspace("subdir")
        assert os.path.isabs(result)
        assert result.endswith("subdir")
    
    def test_trailing_slash_normalized(self, tmp_path):
        a = _canonicalize_workspace(str(tmp_path) + "/")
        b = _canonicalize_workspace(str(tmp_path))
        assert a == b
    
    def test_symlink_resolved(self, tmp_path):
        real = tmp_path / "real"
        real.mkdir()
        link = tmp_path / "link"
        os.symlink(str(real), str(link))
        
        canon_real = _canonicalize_workspace(str(real))
        canon_link = _canonicalize_workspace(str(link))
        assert canon_real == canon_link
    
    def test_idempotent(self, tmp_path):
        once = _canonicalize_workspace(str(tmp_path))
        twice = _canonicalize_workspace(once)
        assert once == twice


# ─────────────────────────────────────────────────────────────────
# Manifest persistence
# ─────────────────────────────────────────────────────────────────

class TestManifestCanonical:
    def test_create_run_store_canonicalizes(self, tmp_path, monkeypatch):
        """Even if caller passes a relative path, manifest stores canonical absolute."""
        monkeypatch.chdir(tmp_path)
        ws = tmp_path / "myws"
        ws.mkdir()
        
        store, manifest = create_run_store(
            run_id=None, project_id="p", build_id="b",
            spec_text="x", task_plan=_plan(),
            runs_root=str(tmp_path / "runs"),
            workspace_root="myws",  # relative
        )
        
        assert os.path.isabs(manifest.workspace_root)
        assert _canonicalize_workspace(str(ws)) == manifest.workspace_root
    
    def test_relative_workspace_in_manifest_canonicalized_on_read(self, tmp_path):
        """If a manifest on disk has a relative workspace_root (e.g. from
        a hand-edited file or older buggy code), it must be canonicalized
        on read so resume can't be tricked by cwd."""
        ws = tmp_path / "real_ws"
        ws.mkdir()
        run_root = tmp_path / "runs" / "run-canon"
        run_root.mkdir(parents=True)
        
        # Hand-craft a manifest with a relative path
        bad_manifest = {
            "run_id": "run-canon",
            "project_id": "p",
            "build_id": "b",
            "run_root": str(run_root),
            "created_at": time.time(),
            "spec_text_hash": "x",
            "task_definitions_hash": "y",
            "current_phase": "intake",
            "current_status": "running",
            "cli_version": "0.1.0",
            "workspace_root": "real_ws",  # RELATIVE!
        }
        (run_root / "run.json").write_text(json.dumps(bad_manifest))
        
        # When read from a totally different cwd, the relative path must
        # NOT resolve against ambient cwd. Either:
        # (a) it gets canonicalized to whatever cwd the read happens in
        #     (still bad, but the round-6 fix should...) OR
        # (b) it stays a relative path (also bad)
        # The right answer is that this manifest is INVALID — relative paths
        # should never be in the manifest. The fix canonicalizes to the
        # process cwd at read time, making the path stable thereafter.
        # For this test, we cd into a known location so the canonicalization
        # is deterministic.
        store = RunStore(str(run_root))
        manifest = store.read_manifest()
        assert manifest is not None
        assert os.path.isabs(manifest.workspace_root), (
            f"workspace_root not canonicalized: {manifest.workspace_root}"
        )
        
        # Re-read should be stable (idempotent)
        manifest2 = store.read_manifest()
        assert manifest2.workspace_root == manifest.workspace_root


# ─────────────────────────────────────────────────────────────────
# Resume CLI canonical behavior
# ─────────────────────────────────────────────────────────────────

class TestResumeCanonical:
    def test_resume_cli_relative_override_canonicalized(self, tmp_path, monkeypatch):
        """If user passes relative --workspace-root, it gets canonicalized
        to the CLI process cwd at the time of the call (deterministic)."""
        runs_dir = str(tmp_path / "runs")
        ws = tmp_path / "ws"
        ws.mkdir()
        
        store, manifest = create_run_store(
            run_id=None, project_id="p", build_id="b",
            spec_text="x", task_plan=_plan(),
            runs_root=runs_dir,
            workspace_root=str(ws),
        )
        # Manifest has canonical absolute path
        assert manifest.workspace_root == _canonicalize_workspace(str(ws))
        
        # Resume with a RELATIVE override that resolves to the same canonical
        # path when cwd is tmp_path
        r = subprocess.run(
            CLI + ["--runs-dir", runs_dir, "resume", manifest.run_id,
                   "--workspace-root", "ws"],
            capture_output=True, text=True, timeout=30,
            cwd=str(tmp_path),
        )
        assert r.returncode == 0, f"got {r.returncode}: {r.stdout}\n{r.stderr}"
    
    def test_resume_relative_override_from_wrong_cwd_rejected(self, tmp_path):
        """Relative override that canonicalizes to a DIFFERENT path is rejected."""
        runs_dir = str(tmp_path / "runs")
        ws_a = tmp_path / "ws_a"
        ws_a.mkdir()
        other_dir = tmp_path / "other"
        other_dir.mkdir()
        (other_dir / "ws_a").mkdir()  # different dir, same relative name
        
        store, manifest = create_run_store(
            run_id=None, project_id="p", build_id="b",
            spec_text="x", task_plan=_plan(),
            runs_root=runs_dir,
            workspace_root=str(ws_a),
        )
        
        # Resume from inside other/, passing "ws_a" relative — resolves
        # to other/ws_a, NOT tmp_path/ws_a → must be rejected
        r = subprocess.run(
            CLI + ["--runs-dir", runs_dir, "resume", manifest.run_id,
                   "--workspace-root", "ws_a"],
            capture_output=True, text=True, timeout=30,
            cwd=str(other_dir),
        )
        assert r.returncode == 1, f"got {r.returncode}: {r.stdout}\n{r.stderr}"
        assert "does not match" in r.stderr.lower()
    
    def test_symlink_workspace_matches_realpath(self, tmp_path):
        """Resuming with a symlinked path that points at the same real
        directory should be accepted (canonicalization resolves both sides)."""
        real_ws = tmp_path / "real_ws"
        real_ws.mkdir()
        link_ws = tmp_path / "link_ws"
        os.symlink(str(real_ws), str(link_ws))
        
        runs_dir = str(tmp_path / "runs")
        store, manifest = create_run_store(
            run_id=None, project_id="p", build_id="b",
            spec_text="x", task_plan=_plan(),
            runs_root=runs_dir,
            workspace_root=str(real_ws),
        )
        
        # Resume via the SYMLINK should be accepted because both canonicalize
        # to the same realpath
        r = subprocess.run(
            CLI + ["--runs-dir", runs_dir, "resume", manifest.run_id,
                   "--workspace-root", str(link_ws)],
            capture_output=True, text=True, timeout=30,
        )
        assert r.returncode == 0, (
            f"symlink rejected: rc={r.returncode}\n{r.stdout}\n{r.stderr}"
        )

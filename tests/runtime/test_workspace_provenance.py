"""Round-5 fix: --workspace-root override on resume must not contradict the manifest."""

import json
import os
import subprocess
import sys
import pytest

from crucible.runtime.run_store import create_run_store, load_run_store


CLI = [sys.executable, "-m", "crucible.runtime.cli"]


def _plan():
    return {
        "spec": "workspace provenance test",
        "project_id": "ws-prov",
        "build_id": "b1",
        "tasks": [{
            "task_id": "t1",
            "description": "verify src/foo.py with tests/test_foo.py",
            "criteria": [{
                "criterion_id": "c1",
                "criterion_class": "must_pass",
                "triple": {
                    "build_target": "non-path-target",
                    "verification_command": "echo PROVENANCE_OK",
                    "expected_output": "PROVENANCE_OK",
                },
            }],
            "role": "builder", "intensity_hint": "S",
        }],
    }


class TestWorkspaceProvenance:
    def test_resume_rejects_mismatched_workspace_override(self, tmp_path):
        """The reviewer's round-5 blocker. Resume must NOT execute in a
        different workspace than the one persisted in run.json — that creates
        an inconsistent run record (manifest says A, events show B)."""
        ws_a = tmp_path / "ws_a"
        ws_b = tmp_path / "ws_b"
        ws_a.mkdir()
        ws_b.mkdir()
        runs_dir = str(tmp_path / "runs")
        
        store, manifest = create_run_store(
            run_id=None, project_id="p", build_id="b",
            spec_text="x", task_plan=_plan(),
            runs_root=runs_dir,
            workspace_root=str(ws_a),
        )
        
        # Try to resume with --workspace-root pointing at a DIFFERENT directory
        r = subprocess.run(
            CLI + ["--runs-dir", runs_dir, "resume", manifest.run_id,
                   "--workspace-root", str(ws_b)],
            capture_output=True, text=True, timeout=30,
        )
        assert r.returncode == 1, (
            f"resume accepted mismatched workspace: rc={r.returncode}\n"
            f"stdout: {r.stdout}\nstderr: {r.stderr}"
        )
        assert "does not match" in r.stderr.lower() or "workspace" in r.stderr.lower()
        
        # Manifest must still say ws_a, not ws_b
        loaded = load_run_store(manifest.run_id, runs_root=runs_dir)
        loaded_manifest = loaded.read_manifest()
        assert loaded_manifest.workspace_root == str(ws_a.resolve()) or \
               loaded_manifest.workspace_root == str(ws_a)
    
    def test_resume_accepts_matching_workspace_override(self, tmp_path):
        """If --workspace-root matches the manifest, it's a no-op and resume proceeds."""
        ws_a = tmp_path / "ws_a"
        ws_a.mkdir()
        runs_dir = str(tmp_path / "runs")
        
        store, manifest = create_run_store(
            run_id=None, project_id="p", build_id="b",
            spec_text="x", task_plan=_plan(),
            runs_root=runs_dir,
            workspace_root=str(ws_a),
        )
        
        r = subprocess.run(
            CLI + ["--runs-dir", runs_dir, "resume", manifest.run_id,
                   "--workspace-root", str(ws_a)],
            capture_output=True, text=True, timeout=30,
        )
        assert r.returncode == 0, f"got {r.returncode}: {r.stdout}\n{r.stderr}"
    
    def test_resume_no_override_uses_manifest(self, tmp_path):
        """Resume with no --workspace-root flag uses the manifest's value."""
        ws_a = tmp_path / "ws_a"
        ws_a.mkdir()
        runs_dir = str(tmp_path / "runs")
        
        store, manifest = create_run_store(
            run_id=None, project_id="p", build_id="b",
            spec_text="x", task_plan=_plan(),
            runs_root=runs_dir,
            workspace_root=str(ws_a),
        )
        
        # Run from a totally unrelated cwd; the manifest should drive workspace
        r = subprocess.run(
            CLI + ["--runs-dir", runs_dir, "resume", manifest.run_id],
            capture_output=True, text=True, timeout=30,
            cwd="/tmp",
        )
        assert r.returncode == 0, f"got {r.returncode}: {r.stdout}\n{r.stderr}"
    
    def test_old_run_first_resume_pins_workspace(self, tmp_path):
        """An old run (no workspace_root in manifest) pinned to a workspace
        on first resume should have that workspace persisted for future resumes."""
        runs_dir = str(tmp_path / "runs")
        store, manifest = create_run_store(
            run_id=None, project_id="p", build_id="b",
            spec_text="x", task_plan=_plan(),
            runs_root=runs_dir,
            # No workspace_root
        )
        assert manifest.workspace_root == ""
        
        # Resume with explicit workspace
        r = subprocess.run(
            CLI + ["--runs-dir", runs_dir, "resume", manifest.run_id,
                   "--workspace-root", str(tmp_path)],
            capture_output=True, text=True, timeout=30,
        )
        assert r.returncode == 0, f"first resume failed: {r.stdout}\n{r.stderr}"
        
        # Manifest should now be pinned
        loaded = load_run_store(manifest.run_id, runs_root=runs_dir)
        loaded_manifest = loaded.read_manifest()
        assert loaded_manifest.workspace_root == str(tmp_path)
        
        # The result file exists from the resume's execute_run, so a second
        # resume returns "already terminal". Clear it to test that the pin
        # actually works for subsequent resumes too.
        os.unlink(loaded.result_path)
        
        r2 = subprocess.run(
            CLI + ["--runs-dir", runs_dir, "resume", manifest.run_id,
                   "--workspace-root", "/some/other/path"],
            capture_output=True, text=True, timeout=30,
        )
        assert r2.returncode == 1, (
            f"second resume should reject mismatched override: {r2.stdout}\n{r2.stderr}"
        )

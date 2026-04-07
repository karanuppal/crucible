"""Round-7 fixes: env-var resume canonicalization + absolute run_root invariant."""

import json
import os
import subprocess
import sys
import pytest

from crucible.runtime.run_store import (
    RunStore, RunManifest, _canonicalize_workspace, create_run_store,
    load_run_store, default_runs_root,
)


CLI = [sys.executable, "-m", "crucible.runtime.cli"]


def _plan():
    return {
        "spec": "path invariant test",
        "project_id": "path-inv",
        "build_id": "b1",
        "tasks": [{
            "task_id": "t1",
            "description": "verify src/foo.py with tests/test_foo.py",
            "criteria": [{
                "criterion_id": "c1",
                "criterion_class": "must_pass",
                "triple": {
                    "build_target": "non-path-target",
                    "verification_command": "echo INVARIANT_OK",
                    "expected_output": "INVARIANT_OK",
                },
            }],
            "role": "builder", "intensity_hint": "S",
        }],
    }


# ─────────────────────────────────────────────────────────────────
# run_root must always be absolute in the manifest
# ─────────────────────────────────────────────────────────────────

class TestAbsoluteRunRoot:
    def test_create_run_store_absolute_runs_root(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        # Pass a RELATIVE runs_root
        store, manifest = create_run_store(
            run_id=None, project_id="p", build_id="b",
            spec_text="x", task_plan=_plan(),
            runs_root="my-runs",  # relative!
            workspace_root=str(tmp_path),
        )
        assert os.path.isabs(manifest.run_root), (
            f"run_root not absolute: {manifest.run_root}"
        )
        assert os.path.isabs(store.run_root)
    
    def test_default_runs_root_absolute(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        # Set env var to a relative path
        monkeypatch.setenv("CRUCIBLE_RUNS_DIR", "rel-runs")
        result = default_runs_root()
        assert os.path.isabs(result), f"default_runs_root not absolute: {result}"
    
    def test_default_runs_root_no_env(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        monkeypatch.delenv("CRUCIBLE_RUNS_DIR", raising=False)
        result = default_runs_root()
        assert os.path.isabs(result)
    
    def test_load_run_store_absolute(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        store, manifest = create_run_store(
            run_id=None, project_id="p", build_id="b",
            spec_text="x", task_plan=_plan(),
            runs_root="rel-runs",
            workspace_root=str(tmp_path),
        )
        run_id = manifest.run_id
        
        # Load via relative path
        loaded = load_run_store(run_id, runs_root="rel-runs")
        assert loaded is not None
        assert os.path.isabs(loaded.run_root)
    
    def test_cli_run_with_relative_runs_dir(self, tmp_path, monkeypatch):
        """Pass a relative --runs-dir to the CLI; manifest must store absolute."""
        plan_path = tmp_path / "plan.json"
        plan_path.write_text(json.dumps(_plan()))
        
        r = subprocess.run(
            CLI + ["--runs-dir", "rel-runs", "run", str(plan_path),
                   "--workspace-root", str(tmp_path)],
            capture_output=True, text=True, timeout=30,
            cwd=str(tmp_path),
        )
        assert r.returncode == 0, f"got {r.returncode}: {r.stdout}\n{r.stderr}"
        
        # Locate the run dir
        runs_dir = tmp_path / "rel-runs"
        assert runs_dir.is_dir()
        run_dirs = list(runs_dir.iterdir())
        assert len(run_dirs) == 1
        manifest = json.loads((run_dirs[0] / "run.json").read_text())
        assert os.path.isabs(manifest["run_root"]), (
            f"manifest.run_root is relative: {manifest['run_root']}"
        )


# ─────────────────────────────────────────────────────────────────
# Env-var resume must canonicalize properly
# ─────────────────────────────────────────────────────────────────

class TestEnvVarResume:
    def test_env_var_workspace_canonicalized_via_helper(self, tmp_path):
        """An old run with empty workspace_root resumed via
        CRUCIBLE_WORKSPACE_ROOT must persist the canonical form (realpath),
        and the executor must use the canonical form too — not the raw env value.
        
        Round-7 reviewer's blocker: env path was only abspath()'d, not
        canonicalized through _canonicalize_workspace, so a symlinked env
        value made the manifest say A while events said B.
        """
        real_ws = tmp_path / "real_ws"
        real_ws.mkdir()
        link_ws = tmp_path / "link_ws"
        os.symlink(str(real_ws), str(link_ws))
        
        runs_dir = str(tmp_path / "runs")
        # Old run with no workspace_root
        store, manifest = create_run_store(
            run_id=None, project_id="p", build_id="b",
            spec_text="x", task_plan=_plan(),
            runs_root=runs_dir,
        )
        
        env = os.environ.copy()
        env["CRUCIBLE_WORKSPACE_ROOT"] = str(link_ws)
        
        r = subprocess.run(
            CLI + ["--runs-dir", runs_dir, "resume", manifest.run_id],
            capture_output=True, text=True, timeout=30,
            env=env,
        )
        assert r.returncode == 0, f"got {r.returncode}: {r.stdout}\n{r.stderr}"
        
        # Manifest must now hold the REALPATH, not the symlink path
        loaded = load_run_store(manifest.run_id, runs_root=runs_dir)
        loaded_manifest = loaded.read_manifest()
        assert loaded_manifest.workspace_root == _canonicalize_workspace(str(real_ws))
        # And not the raw symlink path
        assert loaded_manifest.workspace_root != str(link_ws)
    
    def test_env_var_relative_canonicalized(self, tmp_path):
        """Env var with a relative path: must canonicalize to abs at resume."""
        ws = tmp_path / "rel_ws"
        ws.mkdir()
        runs_dir = str(tmp_path / "runs")
        
        store, manifest = create_run_store(
            run_id=None, project_id="p", build_id="b",
            spec_text="x", task_plan=_plan(),
            runs_root=runs_dir,
        )
        
        env = os.environ.copy()
        env["CRUCIBLE_WORKSPACE_ROOT"] = "rel_ws"  # relative
        
        r = subprocess.run(
            CLI + ["--runs-dir", runs_dir, "resume", manifest.run_id],
            capture_output=True, text=True, timeout=30,
            env=env,
            cwd=str(tmp_path),
        )
        assert r.returncode == 0, f"got {r.returncode}: {r.stdout}\n{r.stderr}"
        
        loaded = load_run_store(manifest.run_id, runs_root=runs_dir)
        loaded_manifest = loaded.read_manifest()
        assert os.path.isabs(loaded_manifest.workspace_root)
        assert loaded_manifest.workspace_root == _canonicalize_workspace(str(ws))

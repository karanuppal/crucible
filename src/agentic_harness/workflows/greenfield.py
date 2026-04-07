"""Phase 5: Greenfield bootstrap.

Scaffolds a new project from an empty directory.
Default backend: Python with uv.
"""

from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Any


class ProjectType(str, Enum):
    PYTHON_CLI = "python_cli"
    PYTHON_LIB = "python_lib"
    PYTHON_API = "python_api"


@dataclass
class BootstrapConfig:
    project_name: str
    project_type: ProjectType
    target_dir: str
    description: str = ""
    python_version: str = "3.13"
    # GitHub remote creation (optional — skipped if create_github_repo=False)
    create_github_repo: bool = False
    github_owner: str = ""  # owner/org for the new repo
    github_visibility: str = "private"  # private | public


@dataclass
class BootstrapState:
    """Persistable state for resumable bootstrap."""
    config: BootstrapConfig
    completed_steps: list[str] = field(default_factory=list)
    failed_step: str = ""
    error_message: str = ""
    is_complete: bool = False
    
    def to_dict(self) -> dict[str, Any]:
        return {
            "config": {
                "project_name": self.config.project_name,
                "project_type": self.config.project_type.value,
                "target_dir": self.config.target_dir,
                "description": self.config.description,
                "python_version": self.config.python_version,
            },
            "completed_steps": list(self.completed_steps),
            "failed_step": self.failed_step,
            "error_message": self.error_message,
            "is_complete": self.is_complete,
        }
    
    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "BootstrapState":
        return cls(
            config=BootstrapConfig(
                project_name=data["config"]["project_name"],
                project_type=ProjectType(data["config"]["project_type"]),
                target_dir=data["config"]["target_dir"],
                description=data["config"].get("description", ""),
                python_version=data["config"].get("python_version", "3.13"),
            ),
            completed_steps=list(data.get("completed_steps", [])),
            failed_step=data.get("failed_step", ""),
            error_message=data.get("error_message", ""),
            is_complete=data.get("is_complete", False),
        )


class BootstrapError(Exception):
    pass


# Step IDs
STEP_CREATE_DIR = "create_dir"
STEP_INIT_PROJECT = "init_project"
STEP_WRITE_README = "write_readme"
STEP_WRITE_GITIGNORE = "write_gitignore"
STEP_WRITE_CI = "write_ci"
STEP_GIT_INIT = "git_init"
STEP_GIT_INITIAL_COMMIT = "git_initial_commit"
STEP_CREATE_GITHUB_REPO = "create_github_repo"
STEP_PUSH_TO_GITHUB = "push_to_github"

ALL_STEPS = [
    STEP_CREATE_DIR,
    STEP_INIT_PROJECT,
    STEP_WRITE_README,
    STEP_WRITE_GITIGNORE,
    STEP_WRITE_CI,
    STEP_GIT_INIT,
    STEP_GIT_INITIAL_COMMIT,
    STEP_CREATE_GITHUB_REPO,
    STEP_PUSH_TO_GITHUB,
]


def _verify_step_artifacts(step_id: str, config: BootstrapConfig) -> bool:
    """Verify that the artifacts for a completed step still exist on disk.
    
    Used for safe resume: don't skip a step if its outputs are missing.
    """
    pkg_name = config.project_name.replace("-", "_")
    target = config.target_dir
    
    if step_id == STEP_CREATE_DIR:
        return os.path.isdir(target)
    if step_id == STEP_INIT_PROJECT:
        return (
            os.path.isfile(os.path.join(target, "pyproject.toml")) and
            os.path.isfile(os.path.join(target, "src", pkg_name, "__init__.py")) and
            os.path.isfile(os.path.join(target, "tests", "test_smoke.py"))
        )
    if step_id == STEP_WRITE_README:
        return os.path.isfile(os.path.join(target, "README.md"))
    if step_id == STEP_WRITE_GITIGNORE:
        return os.path.isfile(os.path.join(target, ".gitignore"))
    if step_id == STEP_WRITE_CI:
        return os.path.isfile(os.path.join(target, ".github", "workflows", "ci.yml"))
    if step_id == STEP_GIT_INIT:
        return os.path.isdir(os.path.join(target, ".git"))
    if step_id == STEP_GIT_INITIAL_COMMIT:
        if not os.path.isdir(os.path.join(target, ".git")):
            return False
        try:
            subprocess.run(
                ["git", "-C", target, "rev-parse", "HEAD"],
                check=True, capture_output=True,
            )
            return True
        except subprocess.CalledProcessError:
            return False
    if step_id == STEP_CREATE_GITHUB_REPO:
        # Best-effort: check via gh
        try:
            result = subprocess.run(
                ["gh", "repo", "view", f"{config.github_owner}/{config.project_name}"],
                capture_output=True, text=True,
            )
            return result.returncode == 0
        except FileNotFoundError:
            return False
    if step_id == STEP_PUSH_TO_GITHUB:
        try:
            result = subprocess.run(
                ["git", "-C", target, "remote", "get-url", "origin"],
                capture_output=True, text=True,
            )
            return result.returncode == 0
        except subprocess.CalledProcessError:
            return False
    return False


def bootstrap_greenfield(
    config: BootstrapConfig,
    state_path: str | None = None,
    state: BootstrapState | None = None,
) -> BootstrapState:
    """Bootstrap a greenfield project. Resumable: skips completed steps.
    
    Resume safety: before skipping a completed step, the step's artifacts
    are verified on disk. If artifacts are missing/damaged, the step is
    re-executed (resume = repair).
    
    On failure: persists state with failed_step set, raises BootstrapError.
    """
    if state is None:
        state = BootstrapState(config=config)
    
    # Drop steps from completed set whose artifacts are missing
    valid_completed = []
    for step in state.completed_steps:
        if _verify_step_artifacts(step, config):
            valid_completed.append(step)
        # else: drop it so the step re-runs
    state.completed_steps = valid_completed
    state.is_complete = False  # force re-verification
    
    completed = set(state.completed_steps)
    
    def _step(step_id: str, fn):
        if step_id in completed:
            return
        try:
            fn()
            state.completed_steps.append(step_id)
            if state_path:
                _save_state(state, state_path)
        except Exception as e:
            state.failed_step = step_id
            state.error_message = str(e)
            if state_path:
                _save_state(state, state_path)
            raise BootstrapError(f"Step {step_id} failed: {e}") from e
    
    _step(STEP_CREATE_DIR, lambda: _create_dir(config))
    _step(STEP_INIT_PROJECT, lambda: _init_project(config))
    _step(STEP_WRITE_README, lambda: _write_readme(config))
    _step(STEP_WRITE_GITIGNORE, lambda: _write_gitignore(config))
    _step(STEP_WRITE_CI, lambda: _write_ci(config))
    _step(STEP_GIT_INIT, lambda: _git_init(config))
    _step(STEP_GIT_INITIAL_COMMIT, lambda: _git_initial_commit(config))
    
    if config.create_github_repo:
        _step(STEP_CREATE_GITHUB_REPO, lambda: _create_github_repo(config))
        _step(STEP_PUSH_TO_GITHUB, lambda: _push_to_github(config))
    
    state.is_complete = True
    state.failed_step = ""
    state.error_message = ""
    if state_path:
        _save_state(state, state_path)
    return state


def _save_state(state: BootstrapState, path: str) -> None:
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(state.to_dict(), f, indent=2)
    os.replace(tmp, path)


def load_bootstrap_state(path: str) -> BootstrapState:
    with open(path) as f:
        return BootstrapState.from_dict(json.load(f))


# ─────────────────────────────────────────────────────────────────
# Step implementations
# ─────────────────────────────────────────────────────────────────

def _create_dir(config: BootstrapConfig) -> None:
    os.makedirs(config.target_dir, exist_ok=True)


def _init_project(config: BootstrapConfig) -> None:
    """Initialize Python project structure."""
    pkg_name = config.project_name.replace("-", "_")
    src_dir = os.path.join(config.target_dir, "src", pkg_name)
    os.makedirs(src_dir, exist_ok=True)
    
    # __init__.py
    with open(os.path.join(src_dir, "__init__.py"), "w") as f:
        f.write(f'"""{config.project_name}"""\n')
    
    # pyproject.toml
    pyproject = f'''[project]
name = "{config.project_name}"
version = "0.1.0"
description = "{config.description}"
requires-python = ">={config.python_version}"
dependencies = []

[dependency-groups]
dev = [
    "pytest>=9.0.0",
    "ruff>=0.15.0",
]

[tool.pytest.ini_options]
testpaths = ["tests"]
pythonpath = ["src"]
'''
    with open(os.path.join(config.target_dir, "pyproject.toml"), "w") as f:
        f.write(pyproject)
    
    # tests dir
    tests_dir = os.path.join(config.target_dir, "tests")
    os.makedirs(tests_dir, exist_ok=True)
    with open(os.path.join(tests_dir, "__init__.py"), "w") as f:
        f.write("")
    
    # smoke test
    with open(os.path.join(tests_dir, "test_smoke.py"), "w") as f:
        f.write(f'''"""Smoke test."""

def test_imports():
    import {pkg_name}
    assert {pkg_name} is not None
''')


def _write_readme(config: BootstrapConfig) -> None:
    path = os.path.join(config.target_dir, "README.md")
    with open(path, "w") as f:
        f.write(f"# {config.project_name}\n\n{config.description}\n")


def _write_gitignore(config: BootstrapConfig) -> None:
    path = os.path.join(config.target_dir, ".gitignore")
    with open(path, "w") as f:
        f.write("__pycache__/\n*.pyc\n.venv/\ndist/\nbuild/\n*.egg-info/\n")


def _write_ci(config: BootstrapConfig) -> None:
    ci_dir = os.path.join(config.target_dir, ".github", "workflows")
    os.makedirs(ci_dir, exist_ok=True)
    path = os.path.join(ci_dir, "ci.yml")
    with open(path, "w") as f:
        f.write(f'''name: CI
on: [push, pull_request]
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v3
      - run: uv sync --all-extras --dev
      - run: uv run pytest
''')


def _git_init(config: BootstrapConfig) -> None:
    subprocess.run(
        ["git", "init", "-q"],
        cwd=config.target_dir, check=True, capture_output=True,
    )


def _create_github_repo(config: BootstrapConfig) -> None:
    """Create a GitHub remote repo using the gh CLI.
    
    Requires gh to be authenticated. Skips if config.create_github_repo is False.
    """
    if not config.github_owner:
        raise BootstrapError("github_owner required when create_github_repo=True")
    
    repo_full = f"{config.github_owner}/{config.project_name}"
    visibility_flag = f"--{config.github_visibility}"
    
    # Check if gh is available
    try:
        subprocess.run(
            ["gh", "auth", "status"],
            check=True, capture_output=True,
        )
    except (FileNotFoundError, subprocess.CalledProcessError) as e:
        raise BootstrapError(f"gh CLI not authenticated: {e}") from e
    
    try:
        subprocess.run(
            ["gh", "repo", "create", repo_full, visibility_flag,
             "--description", config.description or config.project_name],
            check=True, capture_output=True, text=True,
        )
    except subprocess.CalledProcessError as e:
        # If repo already exists, treat as success (idempotent resume)
        if "already exists" in (e.stderr or ""):
            return
        raise BootstrapError(f"gh repo create failed: {e.stderr}") from e


def _push_to_github(config: BootstrapConfig) -> None:
    """Add origin remote and push initial commit."""
    repo_full = f"{config.github_owner}/{config.project_name}"
    remote_url = f"https://github.com/{repo_full}.git"
    
    # Add remote (idempotent: skip if already added)
    try:
        result = subprocess.run(
            ["git", "-C", config.target_dir, "remote", "get-url", "origin"],
            capture_output=True, text=True,
        )
        if result.returncode != 0:
            subprocess.run(
                ["git", "-C", config.target_dir, "remote", "add", "origin", remote_url],
                check=True, capture_output=True, text=True,
            )
    except subprocess.CalledProcessError as e:
        raise BootstrapError(f"Failed to add origin: {e.stderr}") from e
    
    # Push main
    try:
        subprocess.run(
            ["git", "-C", config.target_dir, "push", "-u", "origin", "main"],
            check=True, capture_output=True, text=True,
        )
    except subprocess.CalledProcessError as e:
        # Branch may be 'master' on older git
        try:
            subprocess.run(
                ["git", "-C", config.target_dir, "push", "-u", "origin", "HEAD:main"],
                check=True, capture_output=True, text=True,
            )
        except subprocess.CalledProcessError as e2:
            raise BootstrapError(f"git push failed: {e2.stderr}") from e2


def _git_initial_commit(config: BootstrapConfig) -> None:
    subprocess.run(
        ["git", "-C", config.target_dir, "add", "-A"],
        check=True, capture_output=True,
    )
    # Need a user.email/name for commit
    env = os.environ.copy()
    env.setdefault("GIT_AUTHOR_NAME", "agentic-harness")
    env.setdefault("GIT_AUTHOR_EMAIL", "agent@harness.local")
    env.setdefault("GIT_COMMITTER_NAME", "agentic-harness")
    env.setdefault("GIT_COMMITTER_EMAIL", "agent@harness.local")
    subprocess.run(
        ["git", "-C", config.target_dir, "commit", "-q", "-m", "Initial commit"],
        check=True, capture_output=True, env=env,
    )

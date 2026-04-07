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

ALL_STEPS = [
    STEP_CREATE_DIR,
    STEP_INIT_PROJECT,
    STEP_WRITE_README,
    STEP_WRITE_GITIGNORE,
    STEP_WRITE_CI,
    STEP_GIT_INIT,
    STEP_GIT_INITIAL_COMMIT,
]


def bootstrap_greenfield(
    config: BootstrapConfig,
    state_path: str | None = None,
    state: BootstrapState | None = None,
) -> BootstrapState:
    """Bootstrap a greenfield project. Resumable: skips completed steps.
    
    On failure: persists state with failed_step set, raises BootstrapError.
    """
    if state is None:
        state = BootstrapState(config=config)
    
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

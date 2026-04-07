"""Phase 5 tests: greenfield bootstrap."""

import os
import pytest

from crucible.workflows.greenfield import (
    BootstrapConfig, BootstrapState, ProjectType,
    bootstrap_greenfield, load_bootstrap_state, BootstrapError,
    ALL_STEPS,
)


def _config(tmp_path, name="myproj"):
    return BootstrapConfig(
        project_name=name,
        project_type=ProjectType.PYTHON_LIB,
        target_dir=str(tmp_path / name),
        description="test project",
    )


class TestBootstrap:
    def test_full_bootstrap_creates_structure(self, tmp_path):
        config = _config(tmp_path)
        state = bootstrap_greenfield(config)
        
        assert state.is_complete
        assert os.path.isfile(os.path.join(config.target_dir, "pyproject.toml"))
        assert os.path.isfile(os.path.join(config.target_dir, "README.md"))
        assert os.path.isfile(os.path.join(config.target_dir, ".gitignore"))
        assert os.path.isfile(os.path.join(config.target_dir, ".github", "workflows", "ci.yml"))
        assert os.path.isfile(os.path.join(config.target_dir, "src", "myproj", "__init__.py"))
        assert os.path.isfile(os.path.join(config.target_dir, "tests", "test_smoke.py"))
        assert os.path.isdir(os.path.join(config.target_dir, ".git"))
    
    def test_all_steps_completed(self, tmp_path):
        config = _config(tmp_path)
        state = bootstrap_greenfield(config)
        # Default config has create_github_repo=False, so github steps are skipped
        non_github_steps = [s for s in ALL_STEPS if "github" not in s]
        for step in non_github_steps:
            assert step in state.completed_steps


class TestResume:
    def test_resume_from_partial_state(self, tmp_path):
        config = _config(tmp_path)
        state_path = str(tmp_path / "boot.json")
        
        # Run full bootstrap
        bootstrap_greenfield(config, state_path=state_path)
        
        # Reload and re-run — should be no-op
        loaded = load_bootstrap_state(state_path)
        assert loaded.is_complete
        
        result = bootstrap_greenfield(config, state_path=state_path, state=loaded)
        assert result.is_complete


class TestGitHubFieldsPersistence:
    def test_github_fields_roundtrip(self, tmp_path):
        from crucible.workflows.greenfield import BootstrapState
        config = BootstrapConfig(
            project_name="proj",
            project_type=ProjectType.PYTHON_LIB,
            target_dir=str(tmp_path / "proj"),
            create_github_repo=True,
            github_owner="myorg",
            github_visibility="public",
        )
        state = BootstrapState(config=config)
        d = state.to_dict()
        loaded = BootstrapState.from_dict(d)
        assert loaded.config.create_github_repo is True
        assert loaded.config.github_owner == "myorg"
        assert loaded.config.github_visibility == "public"


class TestPersistence:
    def test_state_persisted(self, tmp_path):
        config = _config(tmp_path)
        state_path = str(tmp_path / "boot.json")
        
        bootstrap_greenfield(config, state_path=state_path)
        
        assert os.path.isfile(state_path)
        loaded = load_bootstrap_state(state_path)
        assert loaded.is_complete
        assert loaded.config.project_name == "myproj"

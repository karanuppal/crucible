"""Phase 5: Unified project workflows.

From spec (§16):
- Existing project inspection
- Branch/worktree isolation
- Greenfield bootstrap
- GitHub repo creation
- CI baseline creation
- First-working-version gate
- Python + uv as defaults
"""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from enum import Enum
from typing import Any


class ProjectMode(str, Enum):
    EXISTING = "existing"
    GREENFIELD = "greenfield"


@dataclass
class ProjectInspection:
    """Results of existing project inspection."""
    mode: ProjectMode
    language: str
    has_package_manager: bool
    package_manager: str  # "uv", "pip", "poetry", "npm", etc.
    has_tests: bool
    test_framework: str
    has_ci: bool
    ci_provider: str  # "github", "gitlab", "none"
    git_remote: str | None


class WorktreeManager:
    """Manages git worktrees for isolation."""
    
    def __init__(self, repo_path: str) -> None:
        self._repo_path = repo_path
    
    def create_worktree(self, branch_name: str, path: str) -> bool:
        """Create an isolated worktree."""
        try:
            result = subprocess.run(
                ["git", "worktree", "add", path, "-b", branch_name],
                cwd=self._repo_path,
                capture_output=True,
                text=True,
            )
            return result.returncode == 0
        except Exception:
            return False
    
    def list_worktrees(self) -> list[dict[str, str]]:
        """List all worktrees."""
        try:
            result = subprocess.run(
                ["git", "worktree", "list", "--porcelain"],
                cwd=self._repo_path,
                capture_output=True,
                text=True,
            )
            if result.returncode != 0:
                return []
            
            worktrees = []
            current = {}
            for line in result.stdout.split("\n"):
                if line.startswith("worktree "):
                    if current:
                        worktrees.append(current)
                    current = {"path": line.split(" ", 1)[1]}
                elif line.startswith("branch "):
                    current["branch"] = line.split(" ", 1)[1]
            if current:
                worktrees.append(current)
            return worktrees
        except Exception:
            return []


class GreenfieldScaffolder:
    """Bootstrap new projects with defaults."""
    
    DEFAULT_TEMPLATES = {
        "python": {
            "package_manager": "uv",
            "test_framework": "pytest",
            "linter": "ruff",
            "ci_template": "github-actions-python",
        },
        "typescript": {
            "package_manager": "npm",
            "test_framework": "vitest",
            "linter": "eslint",
            "ci_template": "github-actions-node",
        },
    }
    
    def scaffold(
        self,
        project_path: str,
        language: str = "python",
        project_name: str = "",
    ) -> dict[str, Any]:
        """Scaffold a new project."""
        template = self.DEFAULT_TEMPLATES.get(language, self.DEFAULT_TEMPLATES["python"])
        
        if not project_name:
            project_name = os.path.basename(project_path)
        
        # Create basic structure
        os.makedirs(project_path, exist_ok=True)
        
        # Create pyproject.toml for Python
        if language == "python":
            pyproject = {
                "project": {
                    "name": project_name,
                    "version": "0.1.0",
                    "requires-python": ">=3.11",
                },
                "dependency-groups": {
                    "dev": ["pytest>=9.0", "ruff>=0.15"],
                },
            }
            import json
            with open(os.path.join(project_path, "pyproject.toml"), "w") as f:
                json.dump(pyproject, f, indent=2)
        
        return {
            "project_name": project_name,
            "language": language,
            "template": template,
        }


class GitHubSetup:
    """GitHub repository and CI setup."""
    
    def __init__(self, token: str | None = None) -> None:
        self._token = token
    
    def create_repo(
        self,
        name: str,
        private: bool = True,
        description: str = "",
    ) -> dict[str, Any]:
        """Create a GitHub repository."""
        # In real implementation, use gh CLI or GitHub API
        # For now, return expected structure
        return {
            "name": name,
            "private": private,
            "description": description,
            "url": f"https://github.com/{name}",
        }
    
    def add_ci_workflow(
        self,
        repo_path: str,
        workflow_name: str,
        workflow_content: dict,
    ) -> bool:
        """Add a CI workflow file."""
        workflow_dir = os.path.join(repo_path, ".github", "workflows")
        os.makedirs(workflow_dir, exist_ok=True)
        
        workflow_file = os.path.join(workflow_dir, f"{workflow_name}.yml")
        
        # Simple YAML-like output (avoiding yaml dependency)
        lines = []
        for key, value in workflow_content.items():
            if isinstance(value, dict):
                lines.append(f"{key}:")
                for k, v in value.items():
                    lines.append(f"  {k}: {v}")
            else:
                lines.append(f"{key}: {value}")
        
        with open(workflow_file, "w") as f:
            f.write("\n".join(lines))
        
        return True


class FirstWorkingVersionGate:
    """The first-working-version gate ensures baseline functionality.
    
    From spec: "first working version gate (no broken tests)"
    """
    
    def __init__(self) -> None:
        self._passed = False
    
    def run(
        self,
        project_path: str,
        test_command: str = "pytest",
    ) -> dict[str, Any]:
        """Run the first-working-version gate."""
        import subprocess
        
        try:
            result = subprocess.run(
                test_command,
                cwd=project_path,
                capture_output=True,
                text=True,
                timeout=120,
            )
            
            passed = result.returncode == 0
            
            return {
                "passed": passed,
                "exit_code": result.returncode,
                "output": result.stdout[-1000:] if result.stdout else "",
                "error": result.stderr[-500:] if result.stderr else "",
            }
        except subprocess.TimeoutExpired:
            return {
                "passed": False,
                "exit_code": -1,
                "output": "",
                "error": "Test command timed out",
            }
        except Exception as e:
            return {
                "passed": False,
                "exit_code": -1,
                "output": "",
                "error": str(e),
            }


def inspect_existing_project(path: str) -> ProjectInspection:
    """Inspect an existing project to determine its structure."""
    mode = ProjectMode.EXISTING
    
    # Detect language
    language = "unknown"
    package_manager = "none"
    has_tests = False
    test_framework = "none"
    has_ci = False
    ci_provider = "none"
    git_remote = None
    
    # Check for Python indicators
    if os.path.exists(os.path.join(path, "pyproject.toml")):
        language = "python"
        package_manager = "uv"
    elif os.path.exists(os.path.join(path, "requirements.txt")):
        language = "python"
        package_manager = "pip"
    
    # Check for test directories
    if os.path.exists(os.path.join(path, "tests")):
        has_tests = True
        test_framework = "pytest"
    
    # Check for CI
    if os.path.exists(os.path.join(path, ".github")):
        has_ci = True
        ci_provider = "github"
    
    # Check git remote
    try:
        result = subprocess.run(
            ["git", "remote", "get-url", "origin"],
            cwd=path,
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            git_remote = result.stdout.strip()
    except Exception:
        pass
    
    # If no indicators found, treat as greenfield
    if language == "unknown" and not git_remote:
        mode = ProjectMode.GREENFIELD
    
    return ProjectInspection(
        mode=mode,
        language=language,
        has_package_manager=package_manager != "none",
        package_manager=package_manager,
        has_tests=has_tests,
        test_framework=test_framework,
        has_ci=has_ci,
        ci_provider=ci_provider,
        git_remote=git_remote,
    )
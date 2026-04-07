"""Phase 7: Fan-in integration workflow.

After multiple sub-agents complete in parallel, the integrator merges
their outputs into a cohesive final result. This module handles:

- Conflict detection across worktrees
- Artifact merging
- Integration validation
- Failure → re-spawn integrator with conflict notes
"""

from __future__ import annotations

import os
import json
import subprocess
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class IntegrationStatus(str, Enum):
    PENDING = "pending"
    MERGING = "merging"
    CONFLICT = "conflict"
    VALIDATED = "validated"
    INTEGRATED = "integrated"
    FAILED = "failed"


@dataclass
class SubAgentOutput:
    """One sub-agent's contribution to integration."""
    task_id: str
    run_id: str
    worktree_path: str
    branch_name: str
    artifact_paths: list[str] = field(default_factory=list)
    summary: str = ""


@dataclass
class IntegrationConflict:
    """A specific conflict between two sub-agent outputs."""
    file_path: str
    conflicting_task_ids: list[str]
    description: str = ""


@dataclass
class IntegrationResult:
    """Final result of fan-in integration."""
    status: IntegrationStatus
    merged_branch: str = ""
    conflicts: list[IntegrationConflict] = field(default_factory=list)
    integrated_paths: list[str] = field(default_factory=list)
    error: str = ""


class IntegrationError(Exception):
    pass


class FanInIntegrator:
    """Merges parallel sub-agent outputs into a single integrated result.
    
    Uses git merge semantics when worktrees are git-based.
    Detects conflicts, classifies them, and either resolves or escalates.
    """
    
    def __init__(self, main_repo_path: str) -> None:
        if not os.path.isdir(main_repo_path):
            raise IntegrationError(f"Main repo not found: {main_repo_path}")
        self._main_repo = main_repo_path
    
    def integrate(
        self,
        outputs: list[SubAgentOutput],
        target_branch: str = "main",
        integration_branch: str | None = None,
    ) -> IntegrationResult:
        """Merge sub-agent outputs into an integration branch.
        
        Strategy:
        1. Create integration branch from target
        2. For each output, attempt to merge its branch
        3. On conflict, capture and continue (collect all conflicts)
        4. Validate the integrated result
        """
        if not outputs:
            return IntegrationResult(status=IntegrationStatus.PENDING)
        
        if integration_branch is None:
            integration_branch = f"integration/build-{int(time.time())}"
        
        env = self._git_env()
        
        # Step 1: create integration branch from target
        try:
            subprocess.run(
                ["git", "-C", self._main_repo, "checkout", "-b", integration_branch, target_branch],
                check=True, capture_output=True, text=True, env=env,
            )
        except subprocess.CalledProcessError as e:
            return IntegrationResult(
                status=IntegrationStatus.FAILED,
                error=f"Failed to create integration branch: {e.stderr}",
            )
        
        # Pre-flight: detect overlaps so conflict reports can attribute properly
        overlap_map = self.detect_overlap(outputs)
        
        # Step 2: merge each output's branch
        conflicts: list[IntegrationConflict] = []
        integrated_paths: list[str] = []
        already_merged_tasks: list[str] = []
        
        for output in outputs:
            try:
                merge_result = subprocess.run(
                    ["git", "-C", self._main_repo, "merge", "--no-ff",
                     "-m", f"Integrate {output.task_id}", output.branch_name],
                    capture_output=True, text=True, env=env,
                )
                if merge_result.returncode != 0:
                    # Merge failed — either conflicts OR a hard error (missing branch etc.)
                    conflict_files = self._get_conflict_files()
                    if conflict_files:
                        # Normal conflict case — collect and abort
                        for cf in conflict_files:
                            attributed = list(overlap_map.get(cf, [output.task_id]))
                            if output.task_id not in attributed:
                                attributed.append(output.task_id)
                            conflicts.append(IntegrationConflict(
                                file_path=cf,
                                conflicting_task_ids=attributed,
                                description=merge_result.stderr[:200],
                            ))
                        subprocess.run(
                            ["git", "-C", self._main_repo, "merge", "--abort"],
                            capture_output=True, text=True, env=env,
                        )
                    else:
                        # Hard failure (missing branch, git error, etc.) — fail closed
                        return IntegrationResult(
                            status=IntegrationStatus.FAILED,
                            merged_branch=integration_branch,
                            error=(
                                f"Merge of {output.branch_name} failed with "
                                f"no conflict files: {merge_result.stderr[:300]}"
                            ),
                        )
                else:
                    integrated_paths.extend(output.artifact_paths)
                    already_merged_tasks.append(output.task_id)
            except subprocess.CalledProcessError as e:
                return IntegrationResult(
                    status=IntegrationStatus.FAILED,
                    error=f"Merge failed for {output.task_id}: {e.stderr}",
                )
        
        if conflicts:
            return IntegrationResult(
                status=IntegrationStatus.CONFLICT,
                merged_branch=integration_branch,
                conflicts=conflicts,
                integrated_paths=integrated_paths,
            )
        
        return IntegrationResult(
            status=IntegrationStatus.INTEGRATED,
            merged_branch=integration_branch,
            integrated_paths=integrated_paths,
        )
    
    def detect_overlap(self, outputs: list[SubAgentOutput]) -> dict[str, list[str]]:
        """Pre-flight: detect files modified by multiple sub-agents.
        
        Returns map of {file_path: [task_ids]}.
        """
        env = self._git_env()
        file_to_tasks: dict[str, list[str]] = {}
        
        for output in outputs:
            try:
                # Get files changed in this branch vs main
                result = subprocess.run(
                    ["git", "-C", self._main_repo, "diff", "--name-only", "main", output.branch_name],
                    capture_output=True, text=True, check=True, env=env,
                )
                changed_files = [f for f in result.stdout.strip().split("\n") if f]
                for f in changed_files:
                    file_to_tasks.setdefault(f, []).append(output.task_id)
            except subprocess.CalledProcessError:
                continue
        
        # Return only files with overlap
        return {f: tasks for f, tasks in file_to_tasks.items() if len(tasks) > 1}
    
    def _get_conflict_files(self) -> list[str]:
        """Get files currently in conflict from git status."""
        env = self._git_env()
        try:
            result = subprocess.run(
                ["git", "-C", self._main_repo, "diff", "--name-only", "--diff-filter=U"],
                capture_output=True, text=True, check=True, env=env,
            )
            return [f for f in result.stdout.strip().split("\n") if f]
        except subprocess.CalledProcessError:
            return []
    
    def _git_env(self) -> dict[str, str]:
        env = os.environ.copy()
        env.setdefault("GIT_AUTHOR_NAME", "agentic-harness")
        env.setdefault("GIT_AUTHOR_EMAIL", "agent@harness.local")
        env.setdefault("GIT_COMMITTER_NAME", "agentic-harness")
        env.setdefault("GIT_COMMITTER_EMAIL", "agent@harness.local")
        return env
    
    def to_report(self, result: IntegrationResult) -> dict[str, Any]:
        """Serialize integration result to a JSON-friendly report."""
        return {
            "status": result.status.value,
            "merged_branch": result.merged_branch,
            "conflict_count": len(result.conflicts),
            "conflicts": [
                {
                    "file": c.file_path,
                    "tasks": list(c.conflicting_task_ids),
                    "description": c.description,
                }
                for c in result.conflicts
            ],
            "integrated_paths": list(result.integrated_paths),
            "error": result.error,
        }

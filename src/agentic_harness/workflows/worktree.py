"""Phase 5: Worktree isolation manager.

Wraps `git worktree` to give each builder run an isolated checkout.
Hard rule: no mutation in worktrees should bleed into the main checkout.
"""

from __future__ import annotations

import os
import subprocess
import json
import uuid
from dataclasses import dataclass, field, asdict
from typing import Any


class WorktreeError(Exception):
    pass


@dataclass
class WorktreeRecord:
    worktree_id: str
    path: str
    branch: str
    main_repo_path: str
    created_at: float
    status: str = "active"  # active | removed


class WorktreeManager:
    """Manages git worktrees for builder isolation.
    
    Persists state so worktree tracking survives restart.
    """
    
    def __init__(self, main_repo_path: str, state_path: str | None = None) -> None:
        if not os.path.isdir(main_repo_path):
            raise WorktreeError(f"Main repo path does not exist: {main_repo_path}")
        self._main_repo = main_repo_path
        self._state_path = state_path
        self._worktrees: dict[str, WorktreeRecord] = {}
        if state_path and os.path.exists(state_path):
            self._load()
    
    def create_worktree(
        self,
        base_branch: str = "main",
        worktree_dir: str | None = None,
    ) -> WorktreeRecord:
        """Create a new isolated worktree branched from base_branch."""
        import time
        
        wt_id = f"wt-{uuid.uuid4().hex[:8]}"
        new_branch = f"build/{wt_id}"
        
        if worktree_dir is None:
            worktree_dir = os.path.join(
                os.path.dirname(self._main_repo),
                f"{os.path.basename(self._main_repo)}-{wt_id}",
            )
        
        try:
            subprocess.run(
                ["git", "-C", self._main_repo, "worktree", "add", "-b", new_branch, worktree_dir, base_branch],
                check=True, capture_output=True, text=True,
            )
        except subprocess.CalledProcessError as e:
            raise WorktreeError(f"Failed to create worktree: {e.stderr}") from e
        
        record = WorktreeRecord(
            worktree_id=wt_id,
            path=worktree_dir,
            branch=new_branch,
            main_repo_path=self._main_repo,
            created_at=time.time(),
        )
        self._worktrees[wt_id] = record
        if self._state_path:
            self._save()
        return record
    
    def remove_worktree(self, worktree_id: str, *, force: bool = False) -> None:
        record = self._worktrees.get(worktree_id)
        if not record:
            return
        
        cmd = ["git", "-C", self._main_repo, "worktree", "remove"]
        if force:
            cmd.append("--force")
        cmd.append(record.path)
        
        try:
            subprocess.run(cmd, check=True, capture_output=True, text=True)
        except subprocess.CalledProcessError as e:
            raise WorktreeError(f"Failed to remove worktree: {e.stderr}") from e
        
        record.status = "removed"
        if self._state_path:
            self._save()
    
    def list_active(self) -> list[WorktreeRecord]:
        return [r for r in self._worktrees.values() if r.status == "active"]
    
    def get(self, worktree_id: str) -> WorktreeRecord | None:
        return self._worktrees.get(worktree_id)
    
    def diff_against_main(self, worktree_id: str) -> str:
        """Return git diff between worktree branch and main branch."""
        record = self._worktrees.get(worktree_id)
        if not record:
            return ""
        try:
            result = subprocess.run(
                ["git", "-C", record.path, "diff", "main"],
                capture_output=True, text=True, check=True,
            )
            return result.stdout
        except subprocess.CalledProcessError:
            return ""
    
    def main_repo_clean(self) -> bool:
        """Verify the main repo checkout is unchanged (no worktree bleed)."""
        try:
            result = subprocess.run(
                ["git", "-C", self._main_repo, "status", "--porcelain"],
                capture_output=True, text=True, check=True,
            )
            return result.stdout.strip() == ""
        except subprocess.CalledProcessError:
            return False
    
    def _save(self) -> None:
        data = {
            "main_repo": self._main_repo,
            "worktrees": {
                wid: asdict(r) for wid, r in self._worktrees.items()
            },
        }
        tmp = self._state_path + ".tmp"
        with open(tmp, "w") as f:
            json.dump(data, f, indent=2)
        os.replace(tmp, self._state_path)
    
    def _load(self) -> None:
        with open(self._state_path) as f:
            data = json.load(f)
        for wid, r_data in data.get("worktrees", {}).items():
            self._worktrees[wid] = WorktreeRecord(**r_data)
        # Reconcile: any "active" worktree whose path no longer exists is stale
        self._reconcile()
    
    def _reconcile(self) -> None:
        """Mark worktrees as stale if their on-disk path or git state is gone.
        
        Fail-closed: if git is unreachable/broken, all active worktrees are
        marked stale (we can't verify them).
        """
        # First try to get git's view
        git_worktree_paths: set[str] | None = None
        try:
            result = subprocess.run(
                ["git", "-C", self._main_repo, "worktree", "list", "--porcelain"],
                capture_output=True, text=True, check=True,
            )
            git_worktree_paths = set()
            for line in result.stdout.splitlines():
                if line.startswith("worktree "):
                    git_worktree_paths.add(line[len("worktree "):].strip())
        except (subprocess.CalledProcessError, FileNotFoundError):
            # Fail-closed: git broken means we can't verify anything
            git_worktree_paths = None
        
        for wid, record in self._worktrees.items():
            if record.status != "active":
                continue
            # Disk check
            if not os.path.isdir(record.path):
                record.status = "stale"
                continue
            # Git check (fail-closed)
            if git_worktree_paths is None:
                record.status = "stale"
            elif record.path not in git_worktree_paths:
                record.status = "stale"
        
        if self._state_path:
            self._save()

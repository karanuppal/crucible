"""Phase 5: First-working-version gate.

A project counts as "working" only when:
1. Tests can be discovered AND run
2. At least one test passes
3. There is executable proof (test output, not just scaffold presence)

This gate must reject scaffolds that look complete but aren't runnable.
"""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass, field
from typing import Any


@dataclass
class FirstWorkingVersionResult:
    is_working: bool
    proof_artifact_path: str  # path to durable proof
    test_count: int = 0
    passed_count: int = 0
    failed_count: int = 0
    error: str = ""


class FirstWorkingVersionError(Exception):
    pass


def check_first_working_version(
    project_dir: str,
    *,
    test_command: list[str] | None = None,
    proof_dir: str | None = None,
    require_real_tests: bool = True,
) -> FirstWorkingVersionResult:
    """Run the project's tests and verify at least one passes.
    
    Hard rule: scaffold-only projects MUST fail this gate.
    
    require_real_tests: if True (default), the project must contain at least
    one Python test file (test_*.py or *_test.py) on disk. This blocks
    forged "1 passed" output from arbitrary scripts.
    """
    if not os.path.isdir(project_dir):
        raise FirstWorkingVersionError(f"Project dir does not exist: {project_dir}")
    
    # Anti-forgery: require actual test files on disk
    if require_real_tests:
        if not _has_real_test_files(project_dir):
            return FirstWorkingVersionResult(
                is_working=False,
                proof_artifact_path="",
                error="No real test files found (test_*.py or *_test.py) — scaffold only or forged output",
            )
    
    if proof_dir is None:
        proof_dir = os.path.join(project_dir, ".harness", "proof")
    os.makedirs(proof_dir, exist_ok=True)
    
    if test_command is None:
        test_command = ["uv", "run", "pytest", "-v"]
    
    proof_path = os.path.join(proof_dir, "first_working_version.txt")
    
    try:
        result = subprocess.run(
            test_command,
            cwd=project_dir,
            capture_output=True,
            text=True,
            timeout=300,
        )
    except subprocess.TimeoutExpired:
        with open(proof_path, "w") as f:
            f.write("TIMEOUT")
        return FirstWorkingVersionResult(
            is_working=False,
            proof_artifact_path=proof_path,
            error="Test command timed out",
        )
    except FileNotFoundError as e:
        return FirstWorkingVersionResult(
            is_working=False,
            proof_artifact_path="",
            error=f"Test command not found: {e}",
        )
    
    output = result.stdout + "\n" + result.stderr
    with open(proof_path, "w") as f:
        f.write(f"COMMAND: {' '.join(test_command)}\n")
        f.write(f"EXIT_CODE: {result.returncode}\n")
        f.write(f"OUTPUT:\n{output}\n")
    
    # Parse pytest output for counts
    test_count, passed_count, failed_count = _parse_pytest_output(output)
    
    is_working = (
        result.returncode == 0
        and passed_count > 0
    )
    
    return FirstWorkingVersionResult(
        is_working=is_working,
        proof_artifact_path=proof_path,
        test_count=test_count,
        passed_count=passed_count,
        failed_count=failed_count,
        error="" if is_working else f"Exit code {result.returncode}, {passed_count} passed",
    )


def _has_real_test_files(project_dir: str) -> bool:
    """Check if the project actually contains test files on disk."""
    for root, dirs, files in os.walk(project_dir):
        # Skip hidden dirs and venvs
        dirs[:] = [d for d in dirs if not d.startswith(".") and d not in {"__pycache__", "node_modules", ".venv", "venv"}]
        for f in files:
            if f.startswith("test_") and f.endswith(".py"):
                return True
            if f.endswith("_test.py"):
                return True
    return False


def _parse_pytest_output(output: str) -> tuple[int, int, int]:
    """Extract test counts from pytest output."""
    import re
    
    passed = 0
    failed = 0
    
    # Match patterns like "5 passed", "2 failed"
    m = re.search(r"(\d+)\s+passed", output)
    if m:
        passed = int(m.group(1))
    
    m = re.search(r"(\d+)\s+failed", output)
    if m:
        failed = int(m.group(1))
    
    return passed + failed, passed, failed

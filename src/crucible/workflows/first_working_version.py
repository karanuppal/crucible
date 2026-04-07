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
    
    # ─────────────────────────────────────────────────────────────
    # Anti-forgery sequence (when require_real_tests=True):
    # 1. Snapshot test file hashes BEFORE any user command runs
    # 2. Run independent pytest FIRST (source of truth)
    # 3. Verify file hashes are unchanged after independent pytest
    # 4. Optionally run user test_command for logging only
    # ─────────────────────────────────────────────────────────────
    
    if require_real_tests:
        # Strict mode: independent pytest is the ONLY trust anchor.
        # User-supplied test_command is NOT executed (it could mutate project state).
        # Hash ALL project files before/after for tamper detection on the verifier itself.
        pre_hashes = _hash_all_project_files(project_dir)
        independent_passed, independent_total = _run_independent_pytest(project_dir)
        post_hashes = _hash_all_project_files(project_dir)
        
        # Detect any mutation outside .harness/proof
        mutated = _diff_hashes_excluding(pre_hashes, post_hashes, exclude_prefix=os.path.join(project_dir, ".harness"))
        if mutated:
            return FirstWorkingVersionResult(
                is_working=False,
                proof_artifact_path="",
                error=f"Project files mutated during pytest run (tamper detected): {sorted(mutated)[:5]}",
            )
        
        if independent_total == 0 or independent_passed == 0:
            return FirstWorkingVersionResult(
                is_working=False,
                proof_artifact_path="",
                test_count=independent_total,
                passed_count=independent_passed,
                error=f"Independent pytest: {independent_passed}/{independent_total} passed",
            )
        
        with open(proof_path, "w") as f:
            f.write(f"INDEPENDENT_PYTEST: {independent_passed}/{independent_total} passed\n")
            f.write(f"NOTE: user test_command not executed in strict mode (anti-tamper)\n")
            f.write(f"FILE_HASH_COUNT: {len(pre_hashes)}\n")
        
        return FirstWorkingVersionResult(
            is_working=True,
            proof_artifact_path=proof_path,
            test_count=independent_total,
            passed_count=independent_passed,
            failed_count=independent_total - independent_passed,
        )
    
    # require_real_tests=False: trust user command (legacy mode)
    try:
        result = subprocess.run(
            test_command, cwd=project_dir,
            capture_output=True, text=True, timeout=300,
        )
    except subprocess.TimeoutExpired:
        with open(proof_path, "w") as f:
            f.write("TIMEOUT")
        return FirstWorkingVersionResult(
            is_working=False, proof_artifact_path=proof_path,
            error="Test command timed out",
        )
    except FileNotFoundError as e:
        return FirstWorkingVersionResult(
            is_working=False, proof_artifact_path="",
            error=f"Test command not found: {e}",
        )
    
    output = result.stdout + "\n" + result.stderr
    with open(proof_path, "w") as f:
        f.write(f"COMMAND: {' '.join(test_command)}\n")
        f.write(f"EXIT_CODE: {result.returncode}\n")
        f.write(f"OUTPUT:\n{output}\n")
    
    test_count, passed_count, failed_count = _parse_pytest_output(output)
    is_working = passed_count > 0 and result.returncode == 0
    
    return FirstWorkingVersionResult(
        is_working=is_working,
        proof_artifact_path=proof_path,
        test_count=test_count,
        passed_count=passed_count,
        failed_count=failed_count,
        error="" if is_working else f"Exit code {result.returncode}, {passed_count} passed",
    )


def _has_real_test_files(project_dir: str) -> bool:
    """Check if the project actually contains test files with real test_* functions.
    
    AST-based: rejects files that just have the right name but no actual tests.
    """
    import ast
    for path in _list_test_files(project_dir):
        try:
            with open(path) as f:
                tree = ast.parse(f.read())
            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    if node.name.startswith("test_"):
                        return True
        except (SyntaxError, OSError):
            continue
    return False


def _hash_test_files(project_dir: str) -> dict[str, str]:
    """Snapshot test file content hashes for tamper detection."""
    import hashlib
    hashes = {}
    for path in _list_test_files(project_dir):
        try:
            with open(path, "rb") as f:
                hashes[path] = hashlib.sha256(f.read()).hexdigest()
        except OSError:
            continue
    return hashes


def _hash_all_project_files(project_dir: str) -> dict[str, str]:
    """Snapshot ALL project files for total tamper detection.
    
    Includes hidden files/dirs (e.g. .env, .config). Skips only known
    cache/build/venv/harness dirs and pyc files.
    """
    import hashlib
    hashes: dict[str, str] = {}
    skip_dirs = {
        "__pycache__", "node_modules", ".venv", "venv", "dist", "build",
        ".harness", ".git", ".pytest_cache", ".ruff_cache", ".mypy_cache",
    }
    for root, dirs, files in os.walk(project_dir):
        dirs[:] = [d for d in dirs if d not in skip_dirs]
        for f in files:
            if f.endswith((".pyc", ".pyo")):
                continue
            full = os.path.join(root, f)
            try:
                if os.path.islink(full):
                    target = os.readlink(full)
                    hashes[full] = f"symlink:{target}"
                else:
                    with open(full, "rb") as fh:
                        hashes[full] = "file:" + hashlib.sha256(fh.read()).hexdigest()
            except OSError:
                hashes[full] = "error"
    return hashes


def _diff_hashes_excluding(
    before: dict[str, str],
    after: dict[str, str],
    exclude_prefix: str = "",
) -> set[str]:
    """Return set of paths that differ between before/after, excluding given prefix."""
    diff: set[str] = set()
    all_keys = set(before.keys()) | set(after.keys())
    for k in all_keys:
        if exclude_prefix and k.startswith(exclude_prefix):
            continue
        if before.get(k) != after.get(k):
            diff.add(k)
    return diff


def _run_independent_pytest(project_dir: str) -> tuple[int, int]:
    """Independently run pytest and return (passed, total).
    
    This is the trust anchor: pytest is invoked directly by the gate,
    not by user-supplied command. Returns (0, 0) if pytest unavailable.
    """
    test_files = _list_test_files(project_dir)
    if not test_files:
        return (0, 0)
    
    try:
        result = subprocess.run(
            ["python", "-m", "pytest", "-q", "--no-header"] + test_files,
            cwd=project_dir,
            capture_output=True,
            text=True,
            timeout=120,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return (0, 0)
    
    out = result.stdout + result.stderr
    _, passed, failed = _parse_pytest_output(out)
    return (passed, passed + failed)


def _extract_test_function_names(project_dir: str) -> set[str]:
    """Parse all test files via AST and return all test_* function names."""
    import ast
    names: set[str] = set()
    for path in _list_test_files(project_dir):
        try:
            with open(path) as f:
                tree = ast.parse(f.read())
            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    if node.name.startswith("test_"):
                        names.add(node.name)
        except (SyntaxError, OSError):
            continue
    return names


def _list_test_files(project_dir: str) -> list[str]:
    """List all test_*.py and *_test.py files in the project."""
    result = []
    for root, dirs, files in os.walk(project_dir):
        dirs[:] = [d for d in dirs if not d.startswith(".") and d not in {"__pycache__", "node_modules", ".venv", "venv"}]
        for f in files:
            if (f.startswith("test_") and f.endswith(".py")) or f.endswith("_test.py"):
                result.append(os.path.join(root, f))
    return result


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

"""Phase 3: Anti-vacuity adversarial revalidation.

Spec §11: "Validation must fail if the claimed implementation could be removed
or clearly broken while validation still passes."

Implementation: re-run the verification triple's command against a stubbed
or removed implementation. If it still PASSes, the criterion was vacuous.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from typing import Callable

from agentic_harness.validation.criterion import (
    Criterion, CriterionResult, CriterionVerdict, VerificationTriple,
)


@dataclass
class VacuityCheckResult:
    criterion_id: str
    is_vacuous: bool
    reason: str


def check_vacuity(
    criterion: Criterion,
    execute_command: Callable[[str], tuple[int, str]],
    stub_impl: Callable[[], None],
    restore_impl: Callable[[], None],
) -> VacuityCheckResult:
    """Adversarial revalidation.
    
    Protocol:
    1. Stub/remove the implementation
    2. Re-run verification command
    3. If it still passes → criterion is vacuous
    4. Restore implementation
    
    Params:
    - execute_command: callable that runs a shell command, returns (exit_code, output)
    - stub_impl: callable that stubs/removes the implementation
    - restore_impl: callable that restores the original implementation
    """
    try:
        stub_impl()
        exit_code, output = execute_command(criterion.triple.verification_command)
        
        # Check if stubbed version still matches expected output (vacuous)
        if criterion.triple.expected_output in output and exit_code == 0:
            return VacuityCheckResult(
                criterion_id=criterion.criterion_id,
                is_vacuous=True,
                reason=f"Verification command passed even with stubbed implementation. Output: {output[:200]}",
            )
        
        return VacuityCheckResult(
            criterion_id=criterion.criterion_id,
            is_vacuous=False,
            reason="Verification correctly failed with stubbed implementation",
        )
    finally:
        restore_impl()


def run_shell_command(cmd: str, cwd: str | None = None, timeout: int = 60) -> tuple[int, str]:
    """Default command executor."""
    try:
        proc = subprocess.run(
            cmd, shell=True, cwd=cwd, capture_output=True, text=True, timeout=timeout,
        )
        return proc.returncode, proc.stdout + proc.stderr
    except subprocess.TimeoutExpired:
        return 124, "TIMEOUT"

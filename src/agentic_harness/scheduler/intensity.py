"""Phase 4: Task intensity classification.

Classifies tasks as LIGHT, MEDIUM, or HEAVY based on:
- Explicit hints (command patterns)
- Task size
- Historical runtime (if available)

Adversarial "looks-light-but-is-heavy" patterns (e.g. "pytest tests/" with big suites)
are detected via heuristic rules.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class Intensity(str, Enum):
    LIGHT = "light"     # <1 CPU, <512MB
    MEDIUM = "medium"   # 1-2 CPU, <2GB
    HEAVY = "heavy"     # >=2 CPU, >=2GB


# Patterns that always indicate HEAVY
HEAVY_PATTERNS = [
    r"\bdocker\s+build\b",
    r"\bcargo\s+build\b",
    r"\bnpm\s+install\b",
    r"\bnpm\s+ci\b",
    r"\byarn\s+install\b",
    r"\bmake\s+all\b",
    r"\bmake\s+test\b",
    r"\bmake\s+build\b",
    r"\bmvn\s+package\b",
    r"\bbazel\b",
    r"\btox\b",
    r"\bplaywright\s+test\b",  # E2E
    r"\bpytest.*--full\b",
    r"\bpytest.*-n\s+auto\b",  # parallel
]


def _normalize_command(cmd: str) -> str:
    """Strip wrappers like 'python -m', 'uv run', 'env X=y' to expose real command."""
    import re as _re
    s = cmd.strip()
    # Strip leading env var assignments (FOO=bar baz)
    s = _re.sub(r"^(?:[A-Z_][A-Z0-9_]*=\S+\s+)+", "", s)
    # Strip wrappers
    wrappers = [
        r"^python\s+-m\s+",
        r"^python3\s+-m\s+",
        r"^uv\s+run\s+",
        r"^poetry\s+run\s+",
        r"^npx\s+",
        r"^pipx\s+run\s+",
    ]
    for w in wrappers:
        s = _re.sub(w, "", s)
    return s


# Patterns that look light but are heavy in practice — checked against normalized command
ADVERSARIAL_HEAVY_PATTERNS = [
    (r"^pytest(?:\s+tests?(/\S*)?)?(?:\s+-[a-zA-Z]+)*\s*$", "full test suite"),
    (r"^pytest\s*$", "full test suite"),
    (r"\bpip\s+install\b", "dependency install"),
    (r"\buv\s+sync\b", "dependency sync"),
    (r"\buv\s+pip\s+install\b", "dependency install"),
]

# Light patterns
LIGHT_PATTERNS = [
    r"\becho\b",
    r"\bls\b",
    r"\bcat\b",
    r"\bpwd\b",
    r"\bpytest.*::test_\w+\b",  # single test
    r"\bpytest.*-k\s+\w+",  # single test by name
    r"\bruff\s+check\b",
]


@dataclass
class IntensityClassification:
    intensity: Intensity
    reason: str
    matched_pattern: str = ""
    adversarial_flag: bool = False


def classify_intensity(
    command: str,
    task_size: str = "M",
    historical_runtime_s: float | None = None,
) -> IntensityClassification:
    """Classify a task's intensity.
    
    Priority:
    1. Normalize command (strip wrappers like 'python -m', 'uv run')
    2. Light single-test patterns (so they match before adversarial)
    3. Adversarial patterns (look-light-heavy) — always HEAVY
    4. Explicit HEAVY patterns
    5. Other LIGHT patterns
    6. Historical runtime
    7. Task size fallback
    """
    normalized = _normalize_command(command)
    
    # Single-test patterns first (so 'pytest tests/test_x.py::test_y' isn't caught by adversarial)
    single_test_patterns = [
        r"\bpytest.*::test_\w+\b",
        r"\bpytest.*-k\s+\w+",
    ]
    for pattern in single_test_patterns:
        if re.search(pattern, normalized):
            return IntensityClassification(
                intensity=Intensity.LIGHT,
                reason="Single test execution",
                matched_pattern=pattern,
            )
    
    # Adversarial — match against normalized
    for pattern, description in ADVERSARIAL_HEAVY_PATTERNS:
        if re.search(pattern, normalized):
            return IntensityClassification(
                intensity=Intensity.HEAVY,
                reason=f"Adversarial pattern matched: {description}",
                matched_pattern=pattern,
                adversarial_flag=True,
            )
    
    for pattern in HEAVY_PATTERNS:
        if re.search(pattern, normalized):
            return IntensityClassification(
                intensity=Intensity.HEAVY,
                reason="Explicit heavy pattern",
                matched_pattern=pattern,
            )
    
    for pattern in LIGHT_PATTERNS:
        if re.search(pattern, normalized):
            return IntensityClassification(
                intensity=Intensity.LIGHT,
                reason="Explicit light pattern",
                matched_pattern=pattern,
            )
    
    # Historical runtime
    if historical_runtime_s is not None:
        if historical_runtime_s > 60:
            return IntensityClassification(
                intensity=Intensity.HEAVY,
                reason=f"Historical runtime {historical_runtime_s}s > 60s",
            )
        elif historical_runtime_s < 5:
            return IntensityClassification(
                intensity=Intensity.LIGHT,
                reason=f"Historical runtime {historical_runtime_s}s < 5s",
            )
    
    # Task size fallback
    size_map = {
        "S": Intensity.LIGHT,
        "M": Intensity.MEDIUM,
        "L": Intensity.HEAVY,
    }
    return IntensityClassification(
        intensity=size_map.get(task_size, Intensity.MEDIUM),
        reason=f"Task size fallback: {task_size}",
    )

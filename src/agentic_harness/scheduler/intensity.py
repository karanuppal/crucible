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
    r"\byarn\s+install\b",
    r"\bmake\s+all\b",
    r"\bmvn\s+package\b",
    r"\bbazel\b",
    r"\btox\b",
    r"\bplaywright\s+test\b",  # E2E
    r"\bpytest.*--full\b",
    r"\bpytest.*-n\s+auto\b",  # parallel
]

# Patterns that might *look* light but are heavy in practice
ADVERSARIAL_HEAVY_PATTERNS = [
    (r"^pytest\s+tests/\s*$", "full test suite"),  # bare pytest tests/
    (r"^pytest\s*$", "full test suite"),
    (r"\bpip\s+install\b", "dependency install"),
    (r"\buv\s+sync\b", "dependency sync"),
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
    1. Adversarial patterns (look-light-heavy) — always HEAVY
    2. Explicit HEAVY patterns
    3. Explicit LIGHT patterns
    4. Historical runtime
    5. Task size fallback
    """
    # Adversarial first — "pytest tests/" looks like light but is full suite
    for pattern, description in ADVERSARIAL_HEAVY_PATTERNS:
        if re.search(pattern, command):
            return IntensityClassification(
                intensity=Intensity.HEAVY,
                reason=f"Adversarial pattern matched: {description}",
                matched_pattern=pattern,
                adversarial_flag=True,
            )
    
    for pattern in HEAVY_PATTERNS:
        if re.search(pattern, command):
            return IntensityClassification(
                intensity=Intensity.HEAVY,
                reason="Explicit heavy pattern",
                matched_pattern=pattern,
            )
    
    for pattern in LIGHT_PATTERNS:
        if re.search(pattern, command):
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

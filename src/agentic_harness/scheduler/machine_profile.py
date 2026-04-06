"""Phase 4: Machine profile and task intensity classifier.

From spec (§12):
- Detect machine capabilities (CPU cores, memory, GPU)
- Classify task intensity (light/medium/heavy)
- Adaptive concurrency heuristics
"""

from __future__ import annotations

import os
import platform
from dataclasses import dataclass
from enum import Enum
from typing import Any


@dataclass
class MachineProfile:
    """Machine capabilities profile."""
    cpu_cores: int
    memory_gb: float
    has_gpu: bool
    gpu_name: str = ""
    platform: str = ""
    python_version: str = ""
    
    @property
    def intensity_score(self) -> float:
        """Compute normalized intensity score (0-1)."""
        score = min(self.cpu_cores / 16, 1.0) * 0.4
        score += min(self.memory_gb / 64, 1.0) * 0.3
        if self.has_gpu:
            score += 0.3
        return score
    
    @property
    def recommended_max_concurrent(self) -> int:
        """Recommended max concurrent tasks."""
        if self.has_gpu:
            return max(2, self.cpu_cores // 4)
        return max(1, self.cpu_cores // 6)


class MachineProfileDetector:
    """Detect machine capabilities."""
    
    def detect(self) -> MachineProfile:
        """Detect and return machine profile."""
        cpu_cores = os.cpu_count() or 4
        
        # Memory detection
        memory_gb = self._detect_memory()
        
        # GPU detection (simplified)
        has_gpu, gpu_name = self._detect_gpu()
        
        return MachineProfile(
            cpu_cores=cpu_cores,
            memory_gb=memory_gb,
            has_gpu=has_gpu,
            gpu_name=gpu_name,
            platform=platform.system(),
            python_version=platform.python_version(),
        )
    
    def _detect_memory(self) -> float:
        """Detect total memory in GB."""
        try:
            if platform.system() == "Darwin":
                import subprocess
                result = subprocess.run(
                    ["sysctl", "-n", "hw.memsize"],
                    capture_output=True, text=True
                )
                if result.returncode == 0:
                    return int(result.stdout.strip()) / (1024 ** 3)
        except Exception:
            pass
        return 8.0  # Default fallback
    
    def _detect_gpu(self) -> tuple[bool, str]:
        """Detect GPU availability."""
        # Simplified: check for common GPU indicators
        try:
            if platform.system() == "Darwin":
                import subprocess
                result = subprocess.run(
                    ["system_profiler", "SPDisplaysDataType"],
                    capture_output=True, text=True
                )
                if result.returncode == 0 and "Apple" in result.stdout:
                    return True, "Apple Silicon"
        except Exception:
            pass
        return False, ""


class TaskIntensity(str, Enum):
    LIGHT = "light"      # < 1 min, no subprocess
    MEDIUM = "medium"   # 1-10 min, simple subprocess
    HEAVY = "heavy"     # > 10 min, complex work


def classify_task_intensity(
    estimated_duration_seconds: float,
    has_subprocess: bool = True,
    memory_intensive: bool = False,
) -> TaskIntensity:
    """Classify task intensity based on characteristics."""
    if estimated_duration_seconds < 60 and not memory_intensive:
        return TaskIntensity.LIGHT
    elif estimated_duration_seconds < 600:
        return TaskIntensity.MEDIUM
    else:
        return TaskIntensity.HEAVY
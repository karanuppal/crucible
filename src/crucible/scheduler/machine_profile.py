"""Phase 4: Machine profile detector.

Detects local machine capacity (CPU, memory, disk) to inform scheduling
decisions. Falls back safely when metrics are unavailable.
"""

from __future__ import annotations

import json
import os
import shutil
from dataclasses import dataclass, asdict
from typing import Any


@dataclass
class MachineProfile:
    """Snapshot of machine capacity."""
    cpu_count: int
    total_memory_gb: float
    available_memory_gb: float
    disk_free_gb: float
    platform: str
    source: str  # "live" or "cached" or "fallback"
    
    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "MachineProfile":
        return cls(**data)
    
    def save(self, path: str) -> None:
        tmp = path + ".tmp"
        with open(tmp, "w") as f:
            json.dump(self.to_dict(), f, indent=2)
        os.replace(tmp, path)
    
    @classmethod
    def load(cls, path: str) -> "MachineProfile":
        with open(path, "r") as f:
            return cls.from_dict(json.load(f))


def detect_machine_profile() -> MachineProfile:
    """Detect the current machine's capacity.
    
    Fails safe: if any metric cannot be read, uses a conservative fallback value.
    """
    import platform as plat
    
    # CPU count
    try:
        cpu_count = os.cpu_count() or 1
    except Exception:
        cpu_count = 1
    
    # Memory — prefer psutil, fall back to os-specific probes
    total_memory_gb = 0.0
    available_memory_gb = 0.0
    try:
        import psutil  # type: ignore
        vm = psutil.virtual_memory()
        total_memory_gb = vm.total / (1024 ** 3)
        available_memory_gb = vm.available / (1024 ** 3)
    except Exception:
        # Catch ANY failure (not just ImportError) and fall back
        # Fallback: sysctl on macOS, /proc/meminfo on Linux
        try:
            if plat.system() == "Darwin":
                import subprocess
                result = subprocess.run(
                    ["sysctl", "-n", "hw.memsize"],
                    capture_output=True, text=True, timeout=5,
                )
                total_memory_gb = int(result.stdout.strip()) / (1024 ** 3)
                available_memory_gb = total_memory_gb * 0.5  # conservative estimate
            elif plat.system() == "Linux":
                with open("/proc/meminfo") as f:
                    for line in f:
                        if line.startswith("MemTotal:"):
                            total_memory_gb = int(line.split()[1]) / (1024 ** 2)
                        elif line.startswith("MemAvailable:"):
                            available_memory_gb = int(line.split()[1]) / (1024 ** 2)
        except Exception:
            pass
    
    # Sanity checks: reject impossible values
    source = "live"
    if total_memory_gb <= 0:
        total_memory_gb = 4.0
        available_memory_gb = 1.0
        source = "fallback"
    if available_memory_gb < 0:
        available_memory_gb = 0.0
        source = "fallback"
    if available_memory_gb > total_memory_gb:
        # Impossible — fall back
        available_memory_gb = total_memory_gb * 0.5
        source = "fallback"
    if cpu_count < 1:
        cpu_count = 1
        source = "fallback"
    
    # Disk
    try:
        disk_stats = shutil.disk_usage("/")
        disk_free_gb = disk_stats.free / (1024 ** 3)
    except Exception:
        disk_free_gb = 1.0
    
    return MachineProfile(
        cpu_count=cpu_count,
        total_memory_gb=round(total_memory_gb, 2),
        available_memory_gb=round(available_memory_gb, 2),
        disk_free_gb=round(disk_free_gb, 2),
        platform=plat.system(),
        source=source,
    )


def fallback_profile() -> MachineProfile:
    """Safe conservative profile when detection fully fails."""
    return MachineProfile(
        cpu_count=1,
        total_memory_gb=4.0,
        available_memory_gb=1.0,
        disk_free_gb=1.0,
        platform="unknown",
        source="fallback",
    )

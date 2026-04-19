"""Static host information — collected once per process, cached for life.

Everything here either cannot change at runtime (chip model, core topology,
total RAM) or changes so infrequently (macOS version, total disk) that a
per-tick refresh would be pure waste. We expose a single ``collect()``
call that lazily fetches the bits on first access and memoises the result
so the ``cool watch`` header can be built on every tick for free.
"""
from __future__ import annotations

import functools
import shutil
import subprocess
from dataclasses import dataclass


@dataclass(frozen=True)
class HostInfo:
    model: str              # e.g. "MacBook Pro"
    chip: str               # e.g. "Apple M1 Max"
    gpu_cores: int | None   # e.g. 32 (from "Apple M1 Max, 32GPU") — None if unknown
    perf_cores: int         # e.g. 8
    eff_cores: int          # e.g. 2
    ram_bytes: int
    disk_total_bytes: int
    macos_version: str      # e.g. "15.2" (Sequoia)

    @property
    def topology(self) -> str:
        """Formatted core topology, e.g. ``"8P+2E"``."""
        return f"{self.perf_cores}P+{self.eff_cores}E"


def _run(cmd: list[str], timeout: float = 1.5) -> str:
    try:
        out = subprocess.check_output(
            cmd, text=True, stderr=subprocess.DEVNULL, timeout=timeout
        )
        return out.strip()
    except (OSError, subprocess.SubprocessError):
        return ""


def _sysctl_int(key: str, default: int = 0) -> int:
    raw = _run(["sysctl", "-n", key])
    try:
        return int(raw)
    except ValueError:
        return default


def _sysctl_str(key: str) -> str:
    return _run(["sysctl", "-n", key])


def _detect_model() -> str:
    # ``system_profiler SPHardwareDataType`` is slow (~400ms) but only runs
    # once. Fall back to the sysctl short code if unavailable.
    raw = _run(["system_profiler", "SPHardwareDataType"], timeout=3.0)
    for line in raw.splitlines():
        if ":" in line:
            k, v = line.split(":", 1)
            if k.strip() == "Model Name":
                return v.strip()
    short = _sysctl_str("hw.model")
    return short or "Mac"


def _detect_chip_and_gpu() -> tuple[str, int | None]:
    # machdep.cpu.brand_string is the canonical source on Apple Silicon.
    brand = _sysctl_str("machdep.cpu.brand_string") or "Apple Silicon"
    gpu_cores: int | None = None
    # Ask system_profiler once for GPU core count (SPDisplaysDataType).
    raw = _run(["system_profiler", "SPDisplaysDataType"], timeout=3.0)
    for line in raw.splitlines():
        stripped = line.strip()
        # macOS >= 13 reports "Total Number of Cores: 32" under the first GPU.
        if stripped.startswith("Total Number of Cores"):
            try:
                gpu_cores = int(stripped.split(":", 1)[1].strip())
                break
            except (IndexError, ValueError):
                continue
    return brand, gpu_cores


def _detect_perf_eff_cores() -> tuple[int, int]:
    perf = _sysctl_int("hw.perflevel0.logicalcpu", 0)
    eff = _sysctl_int("hw.perflevel1.logicalcpu", 0)
    if perf or eff:
        return perf, eff
    # Intel fallback — treat every core as performance.
    total = _sysctl_int("hw.logicalcpu", 0)
    return total, 0


def _detect_disk_total() -> int:
    try:
        return shutil.disk_usage("/").total
    except OSError:
        return 0


def _detect_macos() -> str:
    return _run(["sw_vers", "-productVersion"]) or ""


@functools.lru_cache(maxsize=1)
def collect() -> HostInfo:
    chip, gpu = _detect_chip_and_gpu()
    perf, eff = _detect_perf_eff_cores()
    return HostInfo(
        model=_detect_model(),
        chip=chip,
        gpu_cores=gpu,
        perf_cores=perf,
        eff_cores=eff,
        ram_bytes=_sysctl_int("hw.memsize", 0),
        disk_total_bytes=_detect_disk_total(),
        macos_version=_detect_macos(),
    )

"""Memory + swap + compressor stats derived from vm_stat / sysctl."""
from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass

import psutil


@dataclass
class MemoryStats:
    total: int
    used: int
    available: int
    used_percent: float
    wired: int
    compressed: int
    swap_total: int
    swap_used: int
    page_size: int
    pressure_level: str  # "normal" | "warn" | "critical" | "unknown"


_VM_LINE = re.compile(r"\"?([^\"]+?)\"?:\s+(\d+)")


def _parse_vm_stat() -> tuple[dict[str, int], int]:
    try:
        out = subprocess.run(
            ["vm_stat"], check=True, capture_output=True, text=True, timeout=3
        ).stdout
    except (subprocess.SubprocessError, FileNotFoundError):
        return {}, 16384
    page_size = 16384
    m = re.search(r"page size of (\d+)", out)
    if m:
        page_size = int(m.group(1))
    stats: dict[str, int] = {}
    for line in out.splitlines()[1:]:
        mm = _VM_LINE.match(line.strip())
        if mm:
            stats[mm.group(1).strip()] = int(mm.group(2))
    return stats, page_size


def _swap() -> tuple[int, int]:
    try:
        out = subprocess.run(
            ["sysctl", "-n", "vm.swapusage"], check=True, capture_output=True, text=True, timeout=3
        ).stdout.strip()
    except (subprocess.SubprocessError, FileNotFoundError):
        return 0, 0

    def _to_bytes(token: str) -> int:
        unit = token[-1].upper()
        try:
            n = float(token[:-1])
        except ValueError:
            return 0
        mult = {"K": 1024, "M": 1024**2, "G": 1024**3, "T": 1024**4}.get(unit, 1)
        return int(n * mult)

    total = used = 0
    m_total = re.search(r"total\s*=\s*([\d.]+[KMGT])", out)
    m_used = re.search(r"used\s*=\s*([\d.]+[KMGT])", out)
    if m_total:
        total = _to_bytes(m_total.group(1))
    if m_used:
        used = _to_bytes(m_used.group(1))
    return total, used


def _pressure_level(swap_ratio: float = 0.0, compressed_bytes: int = 0, total_bytes: int = 0) -> str:
    """Coarse memory pressure heuristic combining RAM, swap, and compressor.

    macOS does not expose a single "level" number easily without extra
    frameworks, so we fold three signals into a traffic light.
    """
    try:
        virt = psutil.virtual_memory()
    except Exception:
        return "unknown"

    compressed_ratio = (compressed_bytes / total_bytes) if total_bytes else 0.0

    if virt.percent >= 92 or swap_ratio >= 0.8 or compressed_ratio >= 0.25:
        return "critical"
    if virt.percent >= 80 or swap_ratio >= 0.4 or compressed_ratio >= 0.15:
        return "warn"
    return "normal"


def collect() -> MemoryStats:
    vm, page_size = _parse_vm_stat()
    virt = psutil.virtual_memory()
    wired = vm.get("Pages wired down", 0) * page_size
    compressed = vm.get("Pages occupied by compressor", 0) * page_size
    swap_total, swap_used = _swap()
    swap_ratio = (swap_used / swap_total) if swap_total else 0.0
    return MemoryStats(
        total=virt.total,
        used=virt.used,
        available=virt.available,
        used_percent=virt.percent,
        wired=wired,
        compressed=compressed,
        swap_total=swap_total,
        swap_used=swap_used,
        page_size=page_size,
        pressure_level=_pressure_level(swap_ratio, compressed, virt.total),
    )

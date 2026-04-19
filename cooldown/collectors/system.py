"""Coarse system-level snapshots (CPU load, uptime, total process count)."""
from __future__ import annotations

import os
import time
from dataclasses import dataclass, field

import psutil

from . import hostinfo


@dataclass
class SystemStats:
    cpu_percent: float
    cpu_count_logical: int
    cpu_count_physical: int
    load_1: float
    load_5: float
    load_15: float
    uptime: float
    total_processes: int
    # Per-core CPU usage in the order psutil returns them. On Apple Silicon
    # the first ``perf_cores`` entries are P-cores, the rest are E-cores.
    per_cpu: list[float] = field(default_factory=list)
    # Static Apple-Silicon-aware topology string, e.g. "8P+2E".
    topology: str = ""


def collect(cpu_sample: float = 0.3) -> SystemStats:
    cpu_percent = psutil.cpu_percent(interval=cpu_sample)
    per_cpu = psutil.cpu_percent(interval=None, percpu=True) or []
    la = os.getloadavg()
    host = hostinfo.collect()
    return SystemStats(
        cpu_percent=cpu_percent,
        cpu_count_logical=psutil.cpu_count(logical=True) or 0,
        cpu_count_physical=psutil.cpu_count(logical=False) or 0,
        load_1=la[0],
        load_5=la[1],
        load_15=la[2],
        uptime=time.time() - psutil.boot_time(),
        total_processes=len(psutil.pids()),
        per_cpu=list(per_cpu),
        topology=host.topology,
    )

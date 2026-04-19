"""Coarse system-level snapshots (CPU load, uptime, total process count)."""
from __future__ import annotations

import os
import time
from dataclasses import dataclass

import psutil


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


def collect(cpu_sample: float = 0.3) -> SystemStats:
    cpu_percent = psutil.cpu_percent(interval=cpu_sample)
    la = os.getloadavg()
    return SystemStats(
        cpu_percent=cpu_percent,
        cpu_count_logical=psutil.cpu_count(logical=True) or 0,
        cpu_count_physical=psutil.cpu_count(logical=False) or 0,
        load_1=la[0],
        load_5=la[1],
        load_15=la[2],
        uptime=time.time() - psutil.boot_time(),
        total_processes=len(psutil.pids()),
    )

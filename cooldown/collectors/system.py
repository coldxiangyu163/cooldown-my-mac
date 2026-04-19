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


# Exponential Moving Average smoothing for the live `cool watch` loop.
#
# Raw CPU samples inherit ~±5% quantization noise from macOS's 10ms scheduler
# ticks over a 200ms window. One-shot tools like Mole's `mo status` don't
# expose this because they print once and exit, but a redrawing TUI will show
# the jitter frame-over-frame. A small EMA (alpha ~ 0.3) smooths the display
# to feel like iStat Menus / htop while still reacting within ~2-3 frames to
# real load changes. State is module-global on purpose: only `collect()`
# touches psutil's system-level cpu_percent, so there's no cross-caller
# contention.
_EMA_ALPHA = 0.3
_ema_total: float | None = None
_ema_per_cpu: list[float] | None = None


def _ema(prev: float | None, sample: float, alpha: float = _EMA_ALPHA) -> float:
    if prev is None:
        return sample
    return alpha * sample + (1.0 - alpha) * prev


def reset_smoothing() -> None:
    """Drop any prior EMA state. Call between test cases or when the app
    resumes after a long pause so the first frame shows the real sample
    rather than a stale smoothed value."""
    global _ema_total, _ema_per_cpu
    _ema_total = None
    _ema_per_cpu = None


def collect(cpu_sample: float = 0.3, *, smooth: bool = True) -> SystemStats:
    # Two-call sampling pattern (same as Mole's metrics_cpu.go):
    #   1. warm-up call with interval=None just records the baseline jiffies
    #   2. sleep for the sample window
    #   3. second call returns percentages computed against that baseline
    # Total CPU is derived as the mean of per-core values so the aggregate and
    # the per-core breakdown always come from the *same* sample window and stay
    # self-consistent. Calling cpu_percent(interval=X) followed by an
    # immediate cpu_percent(interval=None, percpu=True) would instead compare
    # two snapshots taken microseconds apart, which is why per-core numbers
    # used to flicker between 0% and 100%.
    if cpu_sample <= 0:
        cpu_sample = 0.2
    psutil.cpu_percent(interval=None, percpu=True)
    psutil.cpu_percent(interval=None)
    time.sleep(cpu_sample)
    per_cpu_raw = list(psutil.cpu_percent(interval=None, percpu=True) or [])
    cpu_percent_raw = (
        sum(per_cpu_raw) / len(per_cpu_raw)
        if per_cpu_raw
        else psutil.cpu_percent(interval=None)
    )

    if smooth:
        global _ema_total, _ema_per_cpu
        cpu_percent = _ema(_ema_total, cpu_percent_raw)
        _ema_total = cpu_percent
        if per_cpu_raw:
            # Reset smoothing state on core-count change (e.g. after a user
            # toggled P/E cluster power). This is extremely rare but cheaper
            # than carrying mismatched arrays forward.
            if _ema_per_cpu is None or len(_ema_per_cpu) != len(per_cpu_raw):
                _ema_per_cpu = list(per_cpu_raw)
            else:
                _ema_per_cpu = [
                    _ema(prev, cur)
                    for prev, cur in zip(_ema_per_cpu, per_cpu_raw, strict=True)
                ]
            per_cpu: list[float] = list(_ema_per_cpu)
        else:
            per_cpu = []
    else:
        cpu_percent = cpu_percent_raw
        per_cpu = per_cpu_raw

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
        per_cpu=per_cpu,
        topology=host.topology,
    )

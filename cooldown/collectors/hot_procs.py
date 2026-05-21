"""TOP-N processes ranked by current CPU usage, regardless of AI-CLI family.

Why this lives alongside ``procs.py`` instead of merging in:
``procs.collect()`` deliberately filters to AI / multiplexer kinds, so a
runaway Python script spawned by hermes-cron or a misbehaving Chrome
renderer never surfaces. ``cool status`` needed a panel that answers
"which PID is burning a core *right now*", which is a strictly different
question from "which AI CLI families are loaded". Keeping them split
avoids cross-cutting changes to ``ProcInfo`` and ``group_by_kind``.

The collector uses the same two-pass cpu_percent pattern as
``procs.collect`` — prime, sleep, then read — and normalizes the result
to a "share of total CPU capacity" percent so values plug directly into
the existing AI CLI Inventory CPU column (which is also normalized).
"""
from __future__ import annotations

import time
from dataclasses import dataclass

import psutil

from ..util import PROC_ERRORS


@dataclass
class HotProc:
    pid: int
    name: str
    cmdline: str
    cpu_percent: float  # normalized to total-CPU share (matches procs.ProcInfo)
    rss: int
    user: str
    create_time: float
    age: float


def collect(top_n: int = 5, sample_interval: float = 0.3) -> list[HotProc]:
    """Return up to ``top_n`` processes ranked by CPU%, descending.

    ``sample_interval`` controls how long we wait between priming and
    reading cpu_percent. Shorter = faster ``cool status`` but noisier
    numbers; longer = more accurate but adds latency. 0.3s is the same
    order of magnitude as ``procs.collect``'s 0.25s default.
    """
    ncpu = psutil.cpu_count(logical=True) or 1

    # First pass: prime CPU accounting for every process. psutil requires
    # at least one prior call before cpu_percent() returns a real value;
    # the first call always reports 0.0.
    primed: list[psutil.Process] = []
    for p in psutil.process_iter(["pid"]):
        try:
            p.cpu_percent(None)
            primed.append(p)
        except PROC_ERRORS:
            continue

    time.sleep(sample_interval)

    # Second pass: read the actual CPU% and snapshot the metadata we
    # need. Skip anything reporting 0% — we only care about hot procs
    # and dropping them keeps the candidate list small for the sort.
    now = time.time()
    rows: list[HotProc] = []
    for p in primed:
        try:
            with p.oneshot():
                raw = p.cpu_percent(None)
                if raw <= 0.0:
                    continue
                cpu = raw / ncpu
                mem = p.memory_info().rss
                ct = p.create_time()
                username = p.username()
                name = p.name()
                try:
                    cmd = " ".join(p.cmdline())
                except PROC_ERRORS:
                    cmd = name
        except PROC_ERRORS:
            continue
        rows.append(
            HotProc(
                pid=p.pid,
                name=name,
                cmdline=cmd,
                cpu_percent=cpu,
                rss=mem,
                user=username,
                create_time=ct,
                age=max(0.0, now - ct),
            )
        )

    rows.sort(key=lambda h: (-h.cpu_percent, h.pid))
    return rows[:top_n]

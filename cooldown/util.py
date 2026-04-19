"""Small cross-module helpers (byte / duration formatting, etc.)."""
from __future__ import annotations

import time

import psutil

# Unified exception tuple for *per-process* psutil probes.
#
# On macOS, reading certain protected processes (Apple-signed system
# services, other users' procs under SIP, etc.) via sysctl KERN_PROCARGS2
# can return EPERM. psutil's C extension wraps this as:
#   - PermissionError / OSError (EPERM/EACCES from the syscall)
#   - SystemError (when the C call "returned a result with an exception set")
# rather than the usual psutil.AccessDenied. Over a long-running loop
# (e.g. `cool watch`) this is guaranteed to hit sooner or later, so every
# call site that touches proc.cmdline() / cwd() / exe() / environ() /
# username() / etc. must catch this unified tuple.
PROC_ERRORS: tuple[type[BaseException], ...] = (
    psutil.NoSuchProcess,
    psutil.AccessDenied,
    psutil.ZombieProcess,
    PermissionError,
    OSError,
    SystemError,
)


def human_bytes(num: float | int) -> str:
    n = float(num)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(n) < 1024.0:
            return f"{n:.1f}{unit}" if unit != "B" else f"{int(n)}{unit}"
        n /= 1024.0
    return f"{n:.1f}PB"


def human_duration(seconds: float | int) -> str:
    s = int(seconds)
    if s < 60:
        return f"{s}s"
    m, s = divmod(s, 60)
    if m < 60:
        return f"{m}m{s:02d}s"
    h, m = divmod(m, 60)
    if h < 24:
        return f"{h}h{m:02d}m"
    d, h = divmod(h, 24)
    return f"{d}d{h:02d}h"


def bar(percent: float, width: int = 20, filled: str = "█", empty: str = "░") -> str:
    percent = max(0.0, min(100.0, percent))
    fill = int(round(width * percent / 100.0))
    return filled * fill + empty * (width - fill)


def now_ts() -> float:
    return time.time()

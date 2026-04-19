"""Small cross-module helpers (byte / duration formatting, etc.)."""
from __future__ import annotations

import time


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

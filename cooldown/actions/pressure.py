"""Pressure guard: evaluate thresholds, compose recommended actions."""
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from ..collectors.memory import MemoryStats


class Severity(StrEnum):
    NORMAL = "normal"
    WARN = "warn"
    CRITICAL = "critical"

    @property
    def rank(self) -> int:
        return {"normal": 0, "warn": 1, "critical": 2}[self.value]


@dataclass
class Thresholds:
    ram_warn: float = 0.80
    ram_crit: float = 0.92
    swap_warn: float = 0.40
    swap_crit: float = 0.80
    compressor_warn: float = 0.15  # share of total RAM
    compressor_crit: float = 0.25


@dataclass
class Signal:
    kind: str  # "ram" | "swap" | "compressor"
    value: float  # ratio 0..1
    severity: Severity
    label: str


@dataclass
class Verdict:
    severity: Severity
    signals: list[Signal]
    recommendations: list[str]


def evaluate(mem: MemoryStats, th: Thresholds | None = None) -> Verdict:
    th = th or Thresholds()
    signals: list[Signal] = []

    ram_ratio = mem.used_percent / 100.0
    signals.append(
        Signal(
            "ram",
            ram_ratio,
            _classify(ram_ratio, th.ram_warn, th.ram_crit),
            f"RAM used {ram_ratio * 100:.1f}%",
        )
    )

    swap_ratio = (mem.swap_used / mem.swap_total) if mem.swap_total else 0.0
    signals.append(
        Signal(
            "swap",
            swap_ratio,
            _classify(swap_ratio, th.swap_warn, th.swap_crit),
            (
                f"Swap {swap_ratio * 100:.1f}% used "
                f"({_bytes(mem.swap_used)} / {_bytes(mem.swap_total)})"
            ),
        )
    )

    compressor_ratio = (mem.compressed / mem.total) if mem.total else 0.0
    signals.append(
        Signal(
            "compressor",
            compressor_ratio,
            _classify(compressor_ratio, th.compressor_warn, th.compressor_crit),
            f"Compressor holds {compressor_ratio * 100:.1f}% of total RAM",
        )
    )

    worst = max(signals, key=lambda s: s.severity.rank).severity
    recs = _recommend(worst, signals)
    return Verdict(worst, signals, recs)


def _classify(value: float, warn: float, crit: float) -> Severity:
    if value >= crit:
        return Severity.CRITICAL
    if value >= warn:
        return Severity.WARN
    return Severity.NORMAL


def _recommend(worst: Severity, signals: list[Signal]) -> list[str]:
    recs: list[str] = []
    if worst is Severity.NORMAL:
        return ["all thresholds green — no action needed"]
    bad = [s for s in signals if s.severity is not Severity.NORMAL]
    if any(s.kind == "swap" and s.severity is Severity.CRITICAL for s in bad):
        recs.append("run `cool reap --ai-idle 1800` to free RSS and let the kernel page back")
        recs.append("consider `sudo purge` to drop disk cache (frees swap pressure)")
    if any(s.kind == "ram" and s.severity is Severity.CRITICAL for s in bad):
        recs.append("close browser tabs / GUI apps not in active use")
    if any(s.kind == "compressor" and s.severity is Severity.CRITICAL for s in bad):
        recs.append("high compressor usage indicates sustained pressure — reboot if 7d+ uptime")
    if worst is Severity.WARN and not recs:
        recs.append("mild pressure — run `cool procs` and trim heavy AI CLIs")
    return recs


def _bytes(n: int) -> str:
    from ..util import human_bytes

    return human_bytes(n)

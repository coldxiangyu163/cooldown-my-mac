from cooldown.actions.pressure import Severity, Thresholds, evaluate
from cooldown.collectors.memory import MemoryStats


def _mem(
    used_percent: float,
    swap_used: int = 0,
    swap_total: int = 0,
    compressed: int = 0,
    total: int = 64 * 1024**3,
) -> MemoryStats:
    return MemoryStats(
        total=total,
        used=int(total * used_percent / 100),
        available=total - int(total * used_percent / 100),
        used_percent=used_percent,
        wired=0,
        compressed=compressed,
        swap_total=swap_total,
        swap_used=swap_used,
        page_size=16384,
        pressure_level="normal",
    )


def test_all_green():
    v = evaluate(_mem(30.0, swap_used=0, swap_total=1024**3, compressed=0))
    assert v.severity is Severity.NORMAL
    assert v.recommendations == ["all thresholds green — no action needed"]


def test_swap_critical_triggers_reap_hint():
    v = evaluate(_mem(60.0, swap_used=9 * 1024**3, swap_total=10 * 1024**3))
    assert v.severity is Severity.CRITICAL
    assert any("cool reap" in r for r in v.recommendations)


def test_ram_warn_only():
    v = evaluate(_mem(85.0, swap_used=0, swap_total=1024**3, compressed=0))
    assert v.severity is Severity.WARN


def test_custom_thresholds_override():
    th = Thresholds(swap_warn=0.1, swap_crit=0.2)
    v = evaluate(_mem(10.0, swap_used=3 * 1024**3, swap_total=10 * 1024**3), th)
    assert v.severity is Severity.CRITICAL


def test_compressor_ratio_counts():
    # 30% of 64GB compressed = clearly critical
    v = evaluate(_mem(30.0, compressed=int(0.3 * 64 * 1024**3)))
    assert v.severity is Severity.CRITICAL

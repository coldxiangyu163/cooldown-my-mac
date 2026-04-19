"""Battery telemetry via ``ioreg -rn AppleSmartBattery``.

macOS exposes a rich battery snapshot through IOKit's ``AppleSmartBattery``
class: cycle count, current + design capacity, cell temperature, charging
rate, and condition. We parse the ``ioreg`` key=value dump rather than
linking against IOKit (avoids adding a C extension) — the cost is one
fork+exec per sample but that's fine on the slow-tick (15s) timer.

All fields are best-effort: every getter returns ``None`` on parse failure
so a missing key never breaks the UI.
"""
from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass


@dataclass(frozen=True)
class BatteryStats:
    # Percent charged, 0-100. None if no battery (desktop Mac).
    percent: float | None
    # Cycle count. Apple rates most current batteries for 1000 cycles.
    cycle_count: int | None
    # Temperature in Celsius (from the cell temp sensor).
    temp_c: float | None
    # Current capacity / design capacity → health %.
    health_percent: float | None
    # Apple's built-in assessment: "Normal" | "Service Recommended" | ...
    condition: str | None
    # True when the adapter is plugged in AND drawing > 0 W into the cell.
    charging: bool
    # True when the adapter is attached (regardless of charging state).
    ac_attached: bool
    # Estimated wattage flowing into the battery. Negative when discharging.
    power_w: float | None
    # Remaining time in minutes ((dis)charge depending on state). None while
    # the kernel is still estimating after a state change.
    minutes_remaining: int | None
    # design / max capacity in mAh (useful for health debugging)
    design_capacity_mah: int | None
    max_capacity_mah: int | None
    # "charged" boolean reported by the kernel — the battery is full AND
    # the adapter is supplying only trickle.
    fully_charged: bool


_RE_INT = re.compile(r'"([^"]+)"\s*=\s*(-?\d+)')
_RE_BOOL = re.compile(r'"([^"]+)"\s*=\s*(Yes|No|True|False)', re.IGNORECASE)
_RE_STR = re.compile(r'"([^"]+)"\s*=\s*"([^"]*)"')


def _parse_ioreg(text: str) -> dict[str, int | str | bool]:
    """Flatten a single ``AppleSmartBattery`` plane dump to key→value.

    We intentionally only keep the *first* value for each key — when
    multiple batteries are present (rare: external packs on the old Mac
    Pro) the primary appears first.
    """
    out: dict[str, int | str | bool] = {}
    for m in _RE_INT.finditer(text):
        out.setdefault(m.group(1), int(m.group(2)))
    for m in _RE_BOOL.finditer(text):
        out.setdefault(m.group(1), m.group(2).lower() in ("yes", "true"))
    for m in _RE_STR.finditer(text):
        out.setdefault(m.group(1), m.group(2))
    return out


def _fetch_ioreg() -> str:
    try:
        return subprocess.check_output(
            ["ioreg", "-rn", "AppleSmartBattery"],
            text=True,
            stderr=subprocess.DEVNULL,
            timeout=2.0,
        )
    except (OSError, subprocess.SubprocessError):
        return ""


def collect() -> BatteryStats | None:
    """Return a :class:`BatteryStats` snapshot, or ``None`` on a desktop
    Mac / when ``ioreg`` is unavailable.
    """
    raw = _fetch_ioreg()
    if not raw:
        return None
    kv = _parse_ioreg(raw)
    # Sanity: no battery plane → nothing to report.
    if not any(k in kv for k in ("MaxCapacity", "AppleRawMaxCapacity")):
        return None

    current = _coerce_int(kv.get("CurrentCapacity"))
    max_cap = _coerce_int(kv.get("MaxCapacity"))
    percent: float | None = None
    # On modern macOS these two are already normalised to a 0-100 scale.
    if current is not None and max_cap:
        percent = round(current / max_cap * 100.0, 1)

    design = _coerce_int(kv.get("DesignCapacity"))
    # ``AppleRawMaxCapacity`` is the real mAh figure (not normalised).
    raw_max = _coerce_int(kv.get("AppleRawMaxCapacity"))
    health: float | None = None
    if design and raw_max:
        health = round(raw_max / design * 100.0, 1)

    # ``Temperature`` is reported in hundredths of a degree Celsius on
    # Apple Silicon (raw=3065 → 30.65°C); Intel Macs use deci-kelvin
    # (raw=30100 → 28°C). Discriminate by plausible cell-temp range: a
    # Li-ion cell outside [-40°C, +80°C] is a sensor fault, not a reading.
    temp_raw = _coerce_int(kv.get("Temperature"))
    temp_c: float | None = None
    if temp_raw is not None:
        candidates = (
            temp_raw / 100.0,         # centi-celsius (Apple Silicon)
            temp_raw / 10.0 - 273.15, # deci-kelvin (Intel Mac)
            float(temp_raw),          # raw celsius (unlikely but some bootcamps)
        )
        for c in candidates:
            if -40.0 <= c <= 80.0:
                temp_c = round(c, 1)
                break

    amperage = _coerce_int(kv.get("InstantAmperage") or kv.get("Amperage"))
    voltage_mv = _coerce_int(kv.get("Voltage"))
    power_w: float | None = None
    if amperage is not None and voltage_mv is not None:
        power_w = round(amperage * voltage_mv / 1_000_000.0, 1)

    return BatteryStats(
        percent=percent,
        cycle_count=_coerce_int(kv.get("CycleCount")),
        temp_c=temp_c,
        health_percent=health,
        condition=_coerce_str(kv.get("BatteryCellDisconnectCount_condition"))
        or _coerce_str(kv.get("Condition")),
        charging=bool(kv.get("IsCharging")),
        ac_attached=bool(kv.get("ExternalConnected")),
        power_w=power_w,
        minutes_remaining=_sanitize_minutes(kv.get("TimeRemaining")
                                              or kv.get("AvgTimeToEmpty")
                                              or kv.get("AvgTimeToFull")),
        design_capacity_mah=design,
        max_capacity_mah=raw_max,
        fully_charged=bool(kv.get("FullyCharged")),
    )


def _coerce_int(v: object) -> int | None:
    if isinstance(v, bool):
        return None
    if isinstance(v, int):
        return v
    if isinstance(v, str):
        try:
            return int(v.strip())
        except ValueError:
            return None
    return None


def _sanitize_minutes(v: object) -> int | None:
    """Some ioreg paths return 65535 / 0xFFFF to mean 'not yet estimated'
    after a power-state change. Filter those sentinels out."""
    n = _coerce_int(v)
    if n is None:
        return None
    if n <= 0 or n >= 60_000:  # > 1000h is nonsense
        return None
    return n


def _coerce_str(v: object) -> str | None:
    if isinstance(v, str) and v.strip():
        return v.strip()
    return None

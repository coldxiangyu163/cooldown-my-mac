"""Thermal + power state (pmset). SMC temps are optional, require sudo."""
from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass


@dataclass
class ThermalStats:
    thermal_warning: str  # "none" | "moderate" | "heavy" | ...
    cpu_power_status: str
    low_power_mode: bool
    ac_power: bool
    battery_percent: int | None
    display_sleep: int | None  # minutes, 0 == never
    disk_sleep: int | None
    sleep_prevented: bool


def _run(cmd: list[str]) -> str:
    try:
        return subprocess.run(
            cmd, check=False, capture_output=True, text=True, timeout=3
        ).stdout
    except (subprocess.SubprocessError, FileNotFoundError):
        return ""


def collect() -> ThermalStats:
    therm_out = _run(["pmset", "-g", "therm"])
    thermal_warning = "none"
    cpu_power_status = "normal"
    m = re.search(r"CPU_Scheduler_Limit\s*=\s*(\d+)", therm_out)
    if m and int(m.group(1)) < 100:
        cpu_power_status = f"throttled({m.group(1)}%)"
    if re.search(r"thermal warning level.*?(\d+)", therm_out, re.I):
        mm = re.search(r"thermal warning level.*?(\d+)", therm_out, re.I)
        if mm and int(mm.group(1)) > 0:
            thermal_warning = f"level{mm.group(1)}"

    pmset_out = _run(["pmset", "-g"])
    def _int_opt(key: str) -> int | None:
        mm = re.search(rf"\b{key}\s+(\d+)", pmset_out)
        return int(mm.group(1)) if mm else None

    low_power = (_int_opt("lowpowermode") or 0) == 1
    display_sleep = _int_opt("displaysleep")
    disk_sleep = _int_opt("disksleep")
    sleep_prevented = "sleep prevented" in pmset_out.lower()

    batt_out = _run(["pmset", "-g", "batt"])
    ac_power = "AC Power" in batt_out
    bm = re.search(r"(\d+)%", batt_out)
    battery_percent = int(bm.group(1)) if bm else None

    return ThermalStats(
        thermal_warning=thermal_warning,
        cpu_power_status=cpu_power_status,
        low_power_mode=low_power,
        ac_power=ac_power,
        battery_percent=battery_percent,
        display_sleep=display_sleep,
        disk_sleep=disk_sleep,
        sleep_prevented=sleep_prevented,
    )

"""Unit tests for :mod:`cooldown.collectors.battery`."""
from __future__ import annotations

import pytest

from cooldown.collectors import battery

IOREG_APPLE_SILICON = '''
+-o AppleSmartBattery  <class AppleSmartBattery>
    {
      "TimeRemaining" = 0
      "AvgTimeToEmpty" = 65535
      "InstantTimeToEmpty" = 65535
      "ExternalConnected" = Yes
      "IsCharging" = No
      "FullyCharged" = Yes
      "CurrentCapacity" = 100
      "MaxCapacity" = 100
      "AppleRawMaxCapacity" = 5184
      "DesignCapacity" = 6075
      "CycleCount" = 95
      "Temperature" = 3065
      "Voltage" = 12850
      "InstantAmperage" = 0
      "Amperage" = 0
      "BatteryCellDisconnectCount" = 0
    }
'''

IOREG_DISCHARGING = '''
+-o AppleSmartBattery  <class AppleSmartBattery>
    {
      "ExternalConnected" = No
      "IsCharging" = No
      "FullyCharged" = No
      "CurrentCapacity" = 78
      "MaxCapacity" = 100
      "AppleRawMaxCapacity" = 5000
      "DesignCapacity" = 5800
      "CycleCount" = 430
      "Temperature" = 3625
      "Voltage" = 11800
      "InstantAmperage" = -1800
      "AvgTimeToEmpty" = 321
    }
'''

IOREG_INTEL_DECI_KELVIN = '''
+-o AppleSmartBattery  <class AppleSmartBattery>
    {
      "ExternalConnected" = Yes
      "IsCharging" = Yes
      "CurrentCapacity" = 72
      "MaxCapacity" = 100
      "AppleRawMaxCapacity" = 4500
      "DesignCapacity" = 5500
      "CycleCount" = 512
      "Temperature" = 3028
      "Voltage" = 12000
      "InstantAmperage" = 1200
    }
'''


def _patch_fetch(monkeypatch: pytest.MonkeyPatch, text: str) -> None:
    monkeypatch.setattr(battery, "_fetch_ioreg", lambda: text)


def test_collect_apple_silicon_idle_plugged_in(monkeypatch):
    _patch_fetch(monkeypatch, IOREG_APPLE_SILICON)
    b = battery.collect()
    assert b is not None
    assert b.percent == 100.0
    assert b.cycle_count == 95
    # 3065 / 100 = 30.65 °C — banker's rounding lands on 30.6, but the
    # exact digit is irrelevant; the point is we're no longer reporting
    # the old bogus -242.5°C deci-kelvin interpretation.
    assert b.temp_c is not None
    assert 30.5 <= b.temp_c <= 30.7
    # 5184 / 6075 ≈ 85.3 %.
    assert b.health_percent == 85.3
    assert b.charging is False
    assert b.ac_attached is True
    assert b.fully_charged is True
    # Sentinel 65535 in AvgTimeToEmpty / TimeRemaining must be scrubbed.
    assert b.minutes_remaining is None
    # 0 A × 12.85 V = 0 W → filtered out / reported as 0.
    assert b.power_w == 0.0


def test_collect_on_battery_gives_negative_power_and_eta(monkeypatch):
    _patch_fetch(monkeypatch, IOREG_DISCHARGING)
    b = battery.collect()
    assert b is not None
    assert b.percent == 78.0
    assert b.temp_c is not None and 36.0 <= b.temp_c <= 36.3  # 3625 / 100
    assert b.ac_attached is False
    assert b.fully_charged is False
    # -1.8 A × 11.8 V ≈ -21.24 W.
    assert b.power_w is not None and b.power_w < 0
    assert b.minutes_remaining == 321


def test_collect_returns_none_without_battery(monkeypatch):
    _patch_fetch(monkeypatch, "")
    assert battery.collect() is None


def test_collect_returns_none_when_no_capacity_key(monkeypatch):
    _patch_fetch(monkeypatch, '+-o AppleSmartBattery\n{\n  "CycleCount" = 3\n}\n')
    assert battery.collect() is None


def test_temp_heuristic_rejects_nonsense_readings(monkeypatch):
    weird = '+-o AppleSmartBattery\n{\n  "MaxCapacity"=100\n  "Temperature"=99999\n}\n'
    _patch_fetch(monkeypatch, weird)
    b = battery.collect()
    assert b is not None
    # 99999 doesn't map to any sane temperature scale → stay silent.
    assert b.temp_c is None


def test_sanitize_minutes_filters_kernel_sentinels():
    assert battery._sanitize_minutes(65535) is None
    assert battery._sanitize_minutes(-1) is None
    assert battery._sanitize_minutes(0) is None
    assert battery._sanitize_minutes(120) == 120
    assert battery._sanitize_minutes("42") == 42
    assert battery._sanitize_minutes("not-a-number") is None

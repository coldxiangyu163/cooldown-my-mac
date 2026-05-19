from rich.console import Console

from cooldown.actions import sleep_policy
from cooldown.collectors.thermal import ThermalStats
from cooldown.collectors.thermal_smc import SmcReading
from cooldown.ui import thermal


def _stub_samples(mocker, *, powernap: bool = True):
    mocker.patch.object(
        thermal.therm_mod,
        "collect",
        return_value=ThermalStats(
            thermal_warning="none",
            cpu_power_status="normal",
            low_power_mode=False,
            ac_power=True,
            battery_percent=80,
            display_sleep=10,
            disk_sleep=10,
            sleep_prevented=False,
        ),
    )
    mocker.patch.object(thermal.smc_mod, "collect", return_value=SmcReading(source="powermetrics"))
    mocker.patch.object(
        thermal.sleep_mod,
        "current",
        return_value=sleep_policy.SleepPolicy(displaysleep=10, disksleep=10, powernap=powernap),
    )


def test_restore_dry_run_reports_preview_without_prompt(mocker):
    _stub_samples(mocker)
    confirm = mocker.patch.object(thermal, "confirm")
    mocker.patch.object(
        thermal.sleep_mod,
        "restore_defaults",
        return_value=sleep_policy.ApplyOutcome(
            True,
            True,
            "dry-run: sudo -n pmset -c displaysleep 10 disksleep 10 powernap 0",
        ),
    )
    console = Console(record=True, force_terminal=False, width=120)

    assert thermal.run(console, restore=True, dry_run=True) == 0

    confirm.assert_not_called()
    assert "dry-run: sudo -n pmset" in console.export_text()


def test_restore_noop_does_not_prompt(mocker):
    _stub_samples(mocker, powernap=False)
    confirm = mocker.patch.object(thermal, "confirm")
    mocker.patch.object(
        thermal.sleep_mod,
        "restore_defaults",
        return_value=sleep_policy.ApplyOutcome(True, False, "no-op: policy already matches"),
    )
    console = Console(record=True, force_terminal=False, width=120)

    assert thermal.run(console, restore=True) == 0

    confirm.assert_not_called()
    assert "no-op: policy already matches" in console.export_text()

import plistlib
import subprocess

from cooldown.collectors import thermal_smc


def _fake_plist() -> bytes:
    data = {
        "smc": {
            "cpu_die_temperature": 52.5,
            "gpu_die_temperature": 48.0,
            "fans": [{"rpm": 1800.0}],
        },
        "processor": {
            "package_watts": 4500,  # mW → expect 4.5W
        },
        "gpu": {
            "gpu_power": 3500,  # mW → expect 3.5W
        },
    }
    return plistlib.dumps(data)


def test_collect_parses_plist(mocker):
    completed = mocker.Mock(returncode=0, stdout=_fake_plist(), stderr=b"")
    mocker.patch.object(subprocess, "run", return_value=completed)

    r = thermal_smc.collect(timeout=0.1)
    assert r.source == "powermetrics"
    assert r.cpu_die_temp == 52.5
    assert r.gpu_die_temp == 48.0
    assert r.fan_rpm == 1800.0
    assert r.package_power_w == 4.5
    assert r.cpu_power_w == 4.5
    assert r.gpu_power_w == 3.5


def test_collect_unavailable_when_sudo_not_cached(mocker):
    completed = mocker.Mock(
        returncode=1,
        stdout=b"",
        stderr=b"sudo: a password is required\n",
    )
    mocker.patch.object(subprocess, "run", return_value=completed)
    r = thermal_smc.collect(timeout=0.1)
    assert r.source == "unavailable"
    assert r.cpu_die_temp is None


def test_collect_unavailable_when_command_missing(mocker):
    mocker.patch.object(subprocess, "run", side_effect=FileNotFoundError)
    r = thermal_smc.collect(timeout=0.1)
    assert r.source == "unavailable"


def test_collect_falls_back_to_text(mocker):
    text = b"""
CPU die temperature: 61.2 C
GPU die temperature: 55.0 C
Fan 0: 2400 rpm
Package Power: 6500 mW
"""
    completed = mocker.Mock(returncode=0, stdout=text, stderr=b"")
    mocker.patch.object(subprocess, "run", return_value=completed)
    r = thermal_smc.collect(timeout=0.1)
    assert r.source == "powermetrics"
    assert r.cpu_die_temp == 61.2
    assert r.gpu_die_temp == 55.0
    assert r.fan_rpm == 2400.0
    assert r.package_power_w == 6.5


def test_sudoers_hint_mentions_powermetrics():
    hint = thermal_smc.sudoers_hint()
    assert "powermetrics" in hint
    assert "NOPASSWD" in hint

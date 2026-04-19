"""Tests for cooldown.daemon.config: defaults, YAML round-trip, validation."""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from cooldown.daemon import config as config_mod


def test_defaults_validate():
    c = config_mod.DaemonConfig()
    assert c.interval_seconds == 60
    assert c.reap.enabled is True
    assert c.reap.ai_idle_seconds == 1800
    assert c.reap.mux_idle_seconds == 14400
    assert c.reap.trigger_severity == "critical"
    assert c.purge.enabled is False
    assert c.notify.enabled is True
    assert c.notify.cooldown_seconds == 300
    assert c.thresholds.ram_warn == pytest.approx(0.80)
    assert c.dry_run is False
    # log_dir should be expanded to an absolute home-rooted path.
    assert Path(str(c.log_dir)).is_absolute()
    assert "~" not in str(c.log_dir)


def test_load_missing_file_returns_defaults(tmp_path: Path):
    missing = tmp_path / "nope.yaml"
    c = config_mod.load(missing)
    assert c.interval_seconds == 60


def test_load_none_uses_default_path(monkeypatch, tmp_path: Path):
    fake = tmp_path / "absent.yaml"
    monkeypatch.setattr(config_mod, "default_path", lambda: fake)
    c = config_mod.load(None)
    assert isinstance(c, config_mod.DaemonConfig)


def test_yaml_round_trip(tmp_path: Path):
    target = tmp_path / "daemon.yaml"
    config_mod.write_default(target)
    assert target.exists()

    # Parse what we wrote — must match the bundled template and validate.
    loaded = config_mod.load(target)
    assert loaded.interval_seconds == 60
    assert loaded.reap.ai_idle_seconds == 1800
    assert loaded.purge.enabled is False
    assert loaded.notify.enabled is True


def test_write_default_refuses_overwrite(tmp_path: Path):
    target = tmp_path / "daemon.yaml"
    target.write_text("already: here\n", encoding="utf-8")
    with pytest.raises(FileExistsError):
        config_mod.write_default(target)
    # With force=True it must replace.
    config_mod.write_default(target, force=True)
    loaded = yaml.safe_load(target.read_text(encoding="utf-8"))
    assert "interval_seconds" in loaded


def test_bad_ratio_raises(tmp_path: Path):
    from pydantic import ValidationError

    target = tmp_path / "bad.yaml"
    target.write_text(
        "thresholds:\n  ram_warn: 3.5\n",
        encoding="utf-8",
    )
    with pytest.raises(ValidationError):
        config_mod.load(target)


def test_bad_interval_raises(tmp_path: Path):
    from pydantic import ValidationError

    target = tmp_path / "bad.yaml"
    target.write_text("interval_seconds: 0\n", encoding="utf-8")
    with pytest.raises(ValidationError):
        config_mod.load(target)


def test_bad_trigger_severity_raises(tmp_path: Path):
    from pydantic import ValidationError

    target = tmp_path / "bad.yaml"
    target.write_text(
        "reap:\n  trigger_severity: yolo\n",
        encoding="utf-8",
    )
    with pytest.raises(ValidationError):
        config_mod.load(target)


def test_top_level_non_mapping_raises(tmp_path: Path):
    target = tmp_path / "bad.yaml"
    target.write_text("- 1\n- 2\n", encoding="utf-8")
    with pytest.raises(ValueError):
        config_mod.load(target)


def test_log_dir_custom_expands(tmp_path: Path):
    target = tmp_path / "daemon.yaml"
    target.write_text("log_dir: ~/somewhere\n", encoding="utf-8")
    c = config_mod.load(target)
    assert "~" not in str(c.log_dir)


def test_default_path_is_under_home():
    p = config_mod.default_path()
    assert p.is_absolute()
    assert p.name == "daemon.yaml"

"""Daemon configuration: pydantic v2 models + YAML load/write helpers."""
from __future__ import annotations

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field, field_validator

TriggerSeverity = Literal["warn", "critical"]


def default_path() -> Path:
    """User-level config path."""
    return Path("~/.config/cooldown/daemon.yaml").expanduser()


def _default_log_dir() -> Path:
    return Path("~/Library/Logs/cooldown").expanduser()


class ThresholdsConfig(BaseModel):
    """Mirrors `cooldown.actions.pressure.Thresholds`."""

    ram_warn: float = 0.80
    ram_crit: float = 0.92
    swap_warn: float = 0.40
    swap_crit: float = 0.80
    compressor_warn: float = 0.15
    compressor_crit: float = 0.25

    @field_validator(
        "ram_warn",
        "ram_crit",
        "swap_warn",
        "swap_crit",
        "compressor_warn",
        "compressor_crit",
    )
    @classmethod
    def _ratio(cls, v: float) -> float:
        if not (0.0 <= v <= 1.0):
            raise ValueError(f"threshold must be between 0.0 and 1.0, got {v}")
        return v


class ReapRule(BaseModel):
    enabled: bool = True
    ai_idle_seconds: int = Field(default=1800, ge=0)
    mux_idle_seconds: int = Field(default=14400, ge=0)
    trigger_severity: TriggerSeverity = "critical"


class PurgeRule(BaseModel):
    enabled: bool = False
    trigger_severity: TriggerSeverity = "critical"
    min_interval_seconds: int = Field(default=1800, ge=0)


class NotifyRule(BaseModel):
    enabled: bool = True
    cooldown_seconds: int = Field(default=300, ge=0)


class DaemonConfig(BaseModel):
    interval_seconds: int = Field(default=60, ge=1)
    thresholds: ThresholdsConfig = Field(default_factory=ThresholdsConfig)
    reap: ReapRule = Field(default_factory=ReapRule)
    purge: PurgeRule = Field(default_factory=PurgeRule)
    notify: NotifyRule = Field(default_factory=NotifyRule)
    dry_run: bool = False
    log_dir: Path = Field(default_factory=_default_log_dir)

    @field_validator("log_dir", mode="before")
    @classmethod
    def _expand_log_dir(cls, v: object) -> Path:
        if v is None:
            return _default_log_dir()
        if isinstance(v, Path):
            return Path(str(v)).expanduser()
        if isinstance(v, str):
            return Path(v).expanduser()
        raise TypeError(f"log_dir must be str or Path, got {type(v).__name__}")


def load(path: Path | str | None) -> DaemonConfig:
    """Load config from `path`. If `path` is None, use `default_path()`.

    Returns defaults when the file does not exist. Raises on invalid YAML or
    schema violations.
    """
    p = Path(path).expanduser() if path is not None else default_path()
    if not p.exists():
        return DaemonConfig()
    with p.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    if not isinstance(data, dict):
        raise ValueError(f"expected a YAML mapping at top level of {p}, got {type(data).__name__}")
    return DaemonConfig.model_validate(data)


def _bundled_default_yaml() -> str:
    return (Path(__file__).parent / "default.yaml").read_text(encoding="utf-8")


def write_default(path: Path | str | None = None, *, force: bool = False) -> Path:
    """Write the commented default YAML template to `path`.

    Refuses to overwrite unless `force=True`. Creates parent dirs as needed.
    """
    p = Path(path).expanduser() if path is not None else default_path()
    if p.exists() and not force:
        raise FileExistsError(p)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(_bundled_default_yaml(), encoding="utf-8")
    return p

"""Daemon runtime: tick loop + rules evaluator.

`run_once(cfg)` evaluates the current system state and fires rules whose
preconditions are met. `loop(cfg)` iterates that tick until SIGTERM/SIGINT
arrives. State (last notification, last purge) is persisted in a small JSON
file under `~/Library/Caches/cooldown/state.json` so cooldowns survive
daemon restarts.
"""
from __future__ import annotations

import json
import logging
import os
import signal
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import psutil

from ..actions import notify as notify_mod
from ..actions import purge as purge_mod
from ..actions.pressure import Severity, Thresholds, evaluate
from ..actions.reap import terminate
from ..collectors import leftovers as leftovers_mod
from ..collectors import memory as mem_mod
from ..collectors import procs as procs_mod
from ..safety.oplog import record
from .config import DaemonConfig

STATE_PATH = Path("~/Library/Caches/cooldown/state.json").expanduser()


# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------


@dataclass
class DaemonState:
    last_notify_ts: float = 0.0
    last_purge_ts: float = 0.0
    last_severity: str = "normal"
    extra: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def load(cls, path: Path | None = None) -> DaemonState:
        path = path if path is not None else STATE_PATH
        try:
            with path.open("r", encoding="utf-8") as f:
                data = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            return cls()
        if not isinstance(data, dict):
            return cls()
        return cls(
            last_notify_ts=float(data.get("last_notify_ts", 0.0) or 0.0),
            last_purge_ts=float(data.get("last_purge_ts", 0.0) or 0.0),
            last_severity=str(data.get("last_severity", "normal")),
            extra={k: v for k, v in data.items() if k not in _KNOWN_STATE_KEYS},
        )

    def save(self, path: Path | None = None) -> None:
        path = path if path is not None else STATE_PATH
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            payload = {
                "last_notify_ts": self.last_notify_ts,
                "last_purge_ts": self.last_purge_ts,
                "last_severity": self.last_severity,
                **self.extra,
            }
            # Atomic write: render to a sibling tmp file, then rename. A
            # daemon crash mid-write previously left state.json truncated
            # and load() would silently start fresh.
            tmp = path.with_suffix(path.suffix + ".tmp")
            with tmp.open("w", encoding="utf-8") as f:
                json.dump(payload, f)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, path)
        except OSError:
            # State is best-effort; never let persistence kill the daemon.
            pass


_KNOWN_STATE_KEYS = {"last_notify_ts", "last_purge_ts", "last_severity"}


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------


def _get_logger(log_dir: Path) -> logging.Logger:
    """Return a logger that appends single-line entries to daemon.log."""
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / "daemon.log"
    logger = logging.getLogger(f"cooldown.daemon.{log_file}")
    if not logger.handlers:
        logger.setLevel(logging.INFO)
        handler = logging.FileHandler(str(log_file), encoding="utf-8")
        handler.setFormatter(logging.Formatter("%(asctime)sZ %(levelname)s %(message)s"))
        handler.formatter.converter = time.gmtime  # type: ignore[assignment]
        logger.addHandler(handler)
        logger.propagate = False
    return logger


# ---------------------------------------------------------------------------
# Rule helpers
# ---------------------------------------------------------------------------


def _severity_meets(current: Severity, trigger: str) -> bool:
    want = Severity(trigger)
    return current.rank >= want.rank


def _severity_is_elevated(s: Severity) -> bool:
    return s is not Severity.NORMAL


# ---------------------------------------------------------------------------
# Tick
# ---------------------------------------------------------------------------


def run_once(cfg: DaemonConfig, *, log: logging.Logger | None = None) -> dict[str, Any]:
    """Evaluate the current system state and apply enabled rules.

    Returns a summary dict describing what happened on this tick. Exceptions
    are caught internally for the reap/purge/notify branches so one broken
    rule does not poison the rest.
    """
    logger = log or _get_logger(cfg.log_dir)
    state = DaemonState.load()
    summary: dict[str, Any] = {"actions": []}

    try:
        mem = mem_mod.collect()
    except Exception as exc:  # noqa: BLE001
        logger.error("collect-memory-failed %s", exc)
        return {"error": str(exc), "actions": []}

    th = Thresholds(
        ram_warn=cfg.thresholds.ram_warn,
        ram_crit=cfg.thresholds.ram_crit,
        swap_warn=cfg.thresholds.swap_warn,
        swap_crit=cfg.thresholds.swap_crit,
        compressor_warn=cfg.thresholds.compressor_warn,
        compressor_crit=cfg.thresholds.compressor_crit,
    )
    verdict = evaluate(mem, th)
    summary["severity"] = verdict.severity.value
    summary["ram"] = mem.used_percent

    record(
        "pressure.eval",
        severity=verdict.severity.value,
        ram=mem.used_percent,
        swap_used=mem.swap_used,
        swap_total=mem.swap_total,
        compressor=mem.compressed,
        source="daemon",
    )

    now = time.time()

    # --- notify rule --------------------------------------------------------
    if cfg.notify.enabled and _severity_is_elevated(verdict.severity):
        elapsed = now - state.last_notify_ts
        severity_changed = verdict.severity.value != state.last_severity
        if severity_changed or elapsed >= cfg.notify.cooldown_seconds:
            title = f"cooldown · {verdict.severity.value.upper()}"
            body = "; ".join(
                s.label for s in verdict.signals if s.severity is not Severity.NORMAL
            ) or "memory pressure detected"
            try:
                if not cfg.dry_run:
                    notify_mod.notify(title, body)
                state.last_notify_ts = now
                summary["actions"].append("notify")
                record(
                    "daemon.notify",
                    severity=verdict.severity.value,
                    dry_run=cfg.dry_run,
                )
            except Exception as exc:  # noqa: BLE001
                logger.error("notify-failed %s", exc)

    # --- reap rule ----------------------------------------------------------
    if cfg.reap.enabled and _severity_meets(verdict.severity, cfg.reap.trigger_severity):
        try:
            procs = procs_mod.collect()
            procs_mod.enrich_idle(procs)
            ai_kinds = procs_mod.AI_KINDS
            mux_kinds = procs_mod.MUX_KINDS
            targets = []
            for p in procs:
                idle = p.idle_seconds or 0
                if (p.kind in ai_kinds and idle >= cfg.reap.ai_idle_seconds) or (
                    p.kind in mux_kinds and idle >= cfg.reap.mux_idle_seconds
                ):
                    targets.append(p)
            if targets:
                outcomes = terminate(targets, dry_run=cfg.dry_run)
                ok = sum(1 for o in outcomes if o.ok)
                summary["actions"].append(f"reap({ok}/{len(outcomes)})")
                record(
                    "daemon.reap",
                    severity=verdict.severity.value,
                    count=len(outcomes),
                    ok=ok,
                    dry_run=cfg.dry_run,
                )
            else:
                summary["actions"].append("reap(0)")
        except Exception as exc:  # noqa: BLE001
            logger.error("reap-failed %s", exc)

    # --- purge rule ---------------------------------------------------------
    if cfg.purge.enabled and _severity_meets(verdict.severity, cfg.purge.trigger_severity):
        elapsed = now - state.last_purge_ts
        if elapsed >= cfg.purge.min_interval_seconds:
            try:
                r = purge_mod.purge(dry_run=cfg.dry_run)
                summary["actions"].append(f"purge({'ok' if r.ok else 'fail'})")
                if r.ok:
                    state.last_purge_ts = now
                record(
                    "daemon.purge",
                    severity=verdict.severity.value,
                    ok=r.ok,
                    needs_sudo=r.needs_sudo,
                    message=r.message,
                    dry_run=cfg.dry_run,
                )
            except Exception as exc:  # noqa: BLE001
                logger.error("purge-failed %s", exc)

    # --- leftovers rule -----------------------------------------------------
    # Independent of memory pressure on purpose: leaked headless Chrome from
    # agent-browser / puppeteer / playwright piles up and cooks the CPU and
    # thermals even when RAM is fine, so this fires every tick when enabled.
    if cfg.leftovers.enabled:
        try:
            items = leftovers_mod.collect(leak_age_seconds=cfg.leftovers.min_age_seconds)
            # The browser branch flags automation Chrome at any age. Reap only
            # what is BOTH old AND quiet: age alone is process lifetime, not
            # inactivity, so a busy session — an in-progress scrape or agent
            # task — is spared no matter how long it has run.
            #
            # "Quiet" is judged per CPU CORE, not as a share of the whole
            # machine. The collector normalizes cpu_percent to raw/ncpu, so a
            # single-threaded session pinning one full core reads as 100/ncpu —
            # tiny on a many-core Mac and wrongly "idle". Multiply ncpu back out
            # so ``busy_cpu_percent`` means single-core utilization (a full core
            # ~= 100), machine-independent.
            ncpu = psutil.cpu_count(logical=True) or 1
            stale = [
                p
                for p in items
                if p.age >= cfg.leftovers.min_age_seconds
                and p.cpu_percent * ncpu <= cfg.leftovers.busy_cpu_percent
            ]
            if stale:
                outcomes = terminate(stale, dry_run=cfg.dry_run)
                ok = sum(1 for o in outcomes if o.ok)
                summary["actions"].append(f"leftovers({ok}/{len(outcomes)})")
                record(
                    "daemon.leftovers",
                    count=len(outcomes),
                    ok=ok,
                    dry_run=cfg.dry_run,
                )
            else:
                summary["actions"].append("leftovers(0)")
        except Exception as exc:  # noqa: BLE001
            logger.error("leftovers-failed %s", exc)

    # --- persist & log ------------------------------------------------------
    state.last_severity = verdict.severity.value
    state.save()

    actions_str = ",".join(summary["actions"]) or "none"
    logger.info(
        "sev=%s ram=%.1f swap=%d/%d actions=%s",
        verdict.severity.value,
        mem.used_percent,
        mem.swap_used,
        mem.swap_total,
        actions_str,
    )
    return summary


# ---------------------------------------------------------------------------
# Loop
# ---------------------------------------------------------------------------


class _StopLoop(Exception):
    """Internal: signal handler raised this to break the loop cleanly."""


def _install_signal_handlers() -> dict[int, Any]:
    """Install SIGTERM/SIGINT handlers that flip a flag the loop watches.

    Returns the previously-installed handlers so the caller can restore them.
    """
    previous: dict[int, Any] = {}

    def _handler(signum: int, _frame: Any) -> None:  # pragma: no cover - signal driven
        raise _StopLoop(f"signal {signum}")

    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            previous[sig] = signal.signal(sig, _handler)
        except (ValueError, OSError):
            # e.g. running in a non-main thread during tests
            continue
    return previous


def _restore_signal_handlers(previous: dict[int, Any]) -> None:
    for sig, handler in previous.items():
        try:
            signal.signal(sig, handler)
        except (ValueError, OSError):  # pragma: no cover
            continue


def loop(cfg: DaemonConfig) -> int:
    """Run the daemon tick loop until a stop signal arrives."""
    logger = _get_logger(cfg.log_dir)
    logger.info(
        "daemon-start interval=%ds dry_run=%s pid=%d ts=%s",
        cfg.interval_seconds,
        cfg.dry_run,
        _pid(),
        datetime.now().isoformat(timespec="seconds"),
    )
    record(
        "daemon.start",
        interval=cfg.interval_seconds,
        dry_run=cfg.dry_run,
    )

    previous = _install_signal_handlers()
    try:
        while True:
            try:
                run_once(cfg, log=logger)
            except _StopLoop:
                raise
            except Exception as exc:  # noqa: BLE001
                logger.error("tick-exception %s", exc)
            # Sleep in small chunks so signals get a prompt response.
            remaining = float(cfg.interval_seconds)
            step = min(1.0, remaining)
            while remaining > 0:
                time.sleep(step)
                remaining -= step
    except _StopLoop as stop:
        logger.info("daemon-stop reason=%s", stop)
        record("daemon.stop", reason=str(stop))
    finally:
        _restore_signal_handlers(previous)
    return 0


def _pid() -> int:
    import os

    return os.getpid()

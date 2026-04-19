"""Runner tests: run_once decision logic with mocked collectors + actions."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from cooldown.collectors.memory import MemoryStats
from cooldown.daemon import runner as runner_mod
from cooldown.daemon.config import DaemonConfig


def _normal_mem() -> MemoryStats:
    total = 32 * 1024**3
    return MemoryStats(
        total=total,
        used=int(total * 0.30),
        available=int(total * 0.70),
        used_percent=30.0,
        wired=0,
        compressed=0,
        swap_total=1024**3,
        swap_used=0,
        page_size=16384,
        pressure_level="normal",
    )


def _critical_mem() -> MemoryStats:
    total = 32 * 1024**3
    return MemoryStats(
        total=total,
        used=int(total * 0.60),
        available=int(total * 0.40),
        used_percent=60.0,
        wired=0,
        compressed=0,
        swap_total=10 * 1024**3,
        swap_used=9 * 1024**3,  # 90% swap -> critical
        page_size=16384,
        pressure_level="critical",
    )


@pytest.fixture
def isolated_state(tmp_path: Path, monkeypatch):
    state_file = tmp_path / "state.json"
    monkeypatch.setattr(runner_mod, "STATE_PATH", state_file)
    return state_file


@pytest.fixture
def temp_log_dir(tmp_path: Path):
    return tmp_path / "logs"


def test_run_once_normal_is_noop(
    monkeypatch, isolated_state: Path, temp_log_dir: Path, tmp_path: Path
):
    monkeypatch.setattr(runner_mod.mem_mod, "collect", lambda: _normal_mem())
    monkeypatch.setattr(runner_mod.procs_mod, "collect", lambda: [])
    monkeypatch.setattr(runner_mod.procs_mod, "enrich_idle", lambda procs: None)

    terminated: list = []
    monkeypatch.setattr(
        runner_mod, "terminate", lambda targets, dry_run=False: terminated.append(targets) or []
    )
    notified: list = []
    monkeypatch.setattr(
        runner_mod.notify_mod, "notify", lambda *a, **k: notified.append(a) or True
    )

    cfg = DaemonConfig(log_dir=temp_log_dir)
    summary = runner_mod.run_once(cfg)
    assert summary["severity"] == "normal"
    assert summary["actions"] == []
    assert terminated == []
    assert notified == []


def test_run_once_critical_swap_reaps_and_notifies(
    monkeypatch, isolated_state: Path, temp_log_dir: Path, tmp_path: Path
):
    from cooldown.collectors.procs import ProcInfo

    idle_droid = ProcInfo(
        pid=424242,
        ppid=1,
        kind="droid",
        name="droid",
        cmdline="droid run",
        rss=100_000_000,
        cpu_percent=0.0,
        create_time=0.0,
        age=9999.0,
        tty=None,
        user="me",
        idle_seconds=99_999.0,
    )

    monkeypatch.setattr(runner_mod.mem_mod, "collect", lambda: _critical_mem())
    monkeypatch.setattr(runner_mod.procs_mod, "collect", lambda: [idle_droid])
    monkeypatch.setattr(runner_mod.procs_mod, "enrich_idle", lambda procs: None)

    terminated_calls: list = []

    def _fake_terminate(targets, *, dry_run=False):
        terminated_calls.append((list(targets), dry_run))
        return [type("O", (), {"ok": True, "pid": t.pid, "kind": t.kind, "cmdline": t.cmdline, "message": "mocked"})() for t in targets]

    monkeypatch.setattr(runner_mod, "terminate", _fake_terminate)
    notified: list = []
    monkeypatch.setattr(
        runner_mod.notify_mod, "notify", lambda *a, **k: notified.append(a) or True
    )

    oplog_entries: list[dict] = []

    def _fake_record(action, **fields):
        oplog_entries.append({"action": action, **fields})

    monkeypatch.setattr(runner_mod, "record", _fake_record)

    cfg = DaemonConfig(log_dir=temp_log_dir)
    summary = runner_mod.run_once(cfg)

    assert summary["severity"] == "critical"
    assert any(a.startswith("reap(") for a in summary["actions"])
    assert "notify" in summary["actions"]
    assert len(terminated_calls) == 1
    assert terminated_calls[0][0][0].pid == 424242

    # oplog must contain a pressure.eval entry with severity=critical
    evals = [e for e in oplog_entries if e["action"] == "pressure.eval"]
    assert evals and evals[0]["severity"] == "critical"

    # State file should now carry last_severity=critical and last_notify_ts>0
    state = json.loads(isolated_state.read_text(encoding="utf-8"))
    assert state["last_severity"] == "critical"
    assert state["last_notify_ts"] > 0


def test_notify_respects_cooldown(
    monkeypatch, isolated_state: Path, temp_log_dir: Path
):
    monkeypatch.setattr(runner_mod.mem_mod, "collect", lambda: _critical_mem())
    monkeypatch.setattr(runner_mod.procs_mod, "collect", lambda: [])
    monkeypatch.setattr(runner_mod.procs_mod, "enrich_idle", lambda procs: None)
    monkeypatch.setattr(runner_mod, "terminate", lambda targets, dry_run=False: [])

    notified: list = []
    monkeypatch.setattr(
        runner_mod.notify_mod, "notify", lambda *a, **k: notified.append(a) or True
    )

    cfg = DaemonConfig(log_dir=temp_log_dir)
    s1 = runner_mod.run_once(cfg)
    s2 = runner_mod.run_once(cfg)

    assert "notify" in s1["actions"]
    # Second immediate call is within cooldown AND same severity; should skip.
    assert "notify" not in s2["actions"]


def test_dry_run_skips_real_terminate_call(
    monkeypatch, isolated_state: Path, temp_log_dir: Path
):
    from cooldown.collectors.procs import ProcInfo

    idle = ProcInfo(
        pid=1234567,
        ppid=1,
        kind="droid",
        name="droid",
        cmdline="droid run",
        rss=1,
        cpu_percent=0.0,
        create_time=0.0,
        age=0.0,
        tty=None,
        user="me",
        idle_seconds=99_999.0,
    )

    monkeypatch.setattr(runner_mod.mem_mod, "collect", lambda: _critical_mem())
    monkeypatch.setattr(runner_mod.procs_mod, "collect", lambda: [idle])
    monkeypatch.setattr(runner_mod.procs_mod, "enrich_idle", lambda procs: None)

    seen: list[bool] = []

    def _term(targets, *, dry_run=False):
        seen.append(dry_run)
        return []

    monkeypatch.setattr(runner_mod, "terminate", _term)
    monkeypatch.setattr(runner_mod.notify_mod, "notify", lambda *a, **k: True)

    cfg = DaemonConfig(log_dir=temp_log_dir, dry_run=True)
    runner_mod.run_once(cfg)
    assert seen == [True]


def test_purge_respects_min_interval(
    monkeypatch, isolated_state: Path, temp_log_dir: Path
):
    from cooldown.actions.purge import PurgeResult
    from cooldown.daemon.config import PurgeRule

    monkeypatch.setattr(runner_mod.mem_mod, "collect", lambda: _critical_mem())
    monkeypatch.setattr(runner_mod.procs_mod, "collect", lambda: [])
    monkeypatch.setattr(runner_mod.procs_mod, "enrich_idle", lambda procs: None)
    monkeypatch.setattr(runner_mod, "terminate", lambda targets, dry_run=False: [])
    monkeypatch.setattr(runner_mod.notify_mod, "notify", lambda *a, **k: True)

    calls: list[int] = []

    def _purge(*, dry_run=False):
        calls.append(1)
        return PurgeResult(True, False, "ok")

    monkeypatch.setattr(runner_mod.purge_mod, "purge", _purge)

    cfg = DaemonConfig(
        log_dir=temp_log_dir,
        purge=PurgeRule(enabled=True, trigger_severity="critical", min_interval_seconds=3600),
    )
    runner_mod.run_once(cfg)
    runner_mod.run_once(cfg)
    # Second call should be blocked by min_interval_seconds.
    assert len(calls) == 1

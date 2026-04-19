"""Tests for cooldown.collectors.services and cooldown.actions.services."""
from __future__ import annotations

import os
import subprocess

import pytest

from cooldown.actions import services as svc_act
from cooldown.collectors import services as svc_mod


def _svc(
    name: str = "redis",
    kind: str = "redis",
    pid: int | None = 1234,
    running: bool = True,
    brew_managed: bool = True,
    brew_status: str | None = "started",
) -> svc_mod.ServiceInfo:
    return svc_mod.ServiceInfo(
        name=name,
        kind=kind,
        pid=pid,
        rss=1_000_000,
        cpu_percent=0.1,
        running=running,
        brew_managed=brew_managed,
        brew_status=brew_status,
    )


def test_classify_brew_names():
    assert svc_mod._classify_brew("redis") == "redis"
    assert svc_mod._classify_brew("postgresql@15") == "postgres"
    assert svc_mod._classify_brew("mongodb-community") == "mongo"
    assert svc_mod._classify_brew("unknown-service") is None


def test_classify_proc_needles():
    assert svc_mod._classify_proc("mysqld", "/opt/homebrew/bin/mysqld --defaults-file=x") == "mysql"
    assert svc_mod._classify_proc("postgres", "postgres: checkpointer") == "postgres"
    assert svc_mod._classify_proc("java", "org.elasticsearch.bootstrap.Elasticsearch") == "elastic"
    assert svc_mod._classify_proc("nginx", "nginx -g daemon off") is None


def test_brew_services_list_empty_when_missing(monkeypatch):
    """When brew is not installed we get an empty list, not a crash."""
    monkeypatch.setattr(svc_mod, "_brew_available", lambda: False)
    assert svc_mod._brew_services_list() == []


def test_brew_services_list_handles_bad_json(monkeypatch):
    monkeypatch.setattr(svc_mod, "_brew_available", lambda: True)

    class FakeProc:
        returncode = 0
        stdout = "not-json"
        stderr = ""

    def fake_run(*_a, **_kw):
        return FakeProc()

    monkeypatch.setattr(svc_mod.subprocess, "run", fake_run)
    assert svc_mod._brew_services_list() == []


def test_brew_services_list_handles_empty_array(monkeypatch):
    monkeypatch.setattr(svc_mod, "_brew_available", lambda: True)

    class FakeProc:
        returncode = 0
        stdout = "[]"
        stderr = ""

    monkeypatch.setattr(svc_mod.subprocess, "run", lambda *_a, **_kw: FakeProc())
    assert svc_mod._brew_services_list() == []


def test_collect_without_brew_uses_process_scan(monkeypatch):
    """If brew isn't installed and no matching processes run, collect() is []."""
    monkeypatch.setattr(svc_mod, "_brew_services_list", lambda: [])
    monkeypatch.setattr(svc_mod, "_scan_processes", lambda: {})
    assert svc_mod.collect() == []


def test_start_dry_run_does_not_run_brew(monkeypatch):
    called = {"n": 0}

    def fake_run_brew(*_a, **_kw):
        called["n"] += 1
        return True, "ok"

    monkeypatch.setattr(svc_act, "_run_brew", fake_run_brew)
    out = svc_act.start(_svc(running=False, brew_status="stopped"), dry_run=True)
    assert out.ok is True
    assert "dry-run" in out.message
    assert called["n"] == 0


def test_stop_dry_run_does_not_signal(monkeypatch):
    def boom(*_a, **_kw):
        raise AssertionError("must not signal in dry-run")

    monkeypatch.setattr(svc_act, "_terminate_pid", boom)
    monkeypatch.setattr(svc_act, "_run_brew", boom)
    out = svc_act.stop(_svc(), dry_run=True)
    assert out.ok is True
    assert "dry-run" in out.message


def test_stop_self_protection(monkeypatch):
    """Never stop a service whose pid is us or one of our ancestors."""
    me = os.getpid()
    monkeypatch.setattr(svc_act, "_brew_available", lambda: False)
    svc = _svc(pid=me, brew_managed=False, brew_status=None)
    out = svc_act.stop(svc, dry_run=False)
    assert out.ok is False
    assert "protected" in out.message


def test_stop_no_pid_without_brew_fails(monkeypatch):
    monkeypatch.setattr(svc_act, "_brew_available", lambda: False)
    out = svc_act.stop(_svc(pid=None, brew_managed=False, brew_status=None), dry_run=False)
    assert out.ok is False
    assert "no pid" in out.message


def test_stop_via_brew(monkeypatch):
    monkeypatch.setattr(svc_act, "_brew_available", lambda: True)
    monkeypatch.setattr(svc_act, "_run_brew", lambda *a, **kw: (True, "stopped redis"))
    out = svc_act.stop(_svc(), dry_run=False)
    assert out.ok is True
    assert "stopped" in out.message


def test_start_cannot_start_unmanaged(monkeypatch):
    monkeypatch.setattr(svc_act, "_brew_available", lambda: False)
    out = svc_act.start(
        _svc(running=False, brew_managed=False, brew_status=None),
        dry_run=False,
    )
    assert out.ok is False
    assert "cannot start" in out.message


def test_run_brew_propagates_failure(monkeypatch):
    class FakeProc:
        returncode = 1
        stdout = ""
        stderr = "Error: nope"

    monkeypatch.setattr(svc_act.subprocess, "run", lambda *a, **kw: FakeProc())
    ok, msg = svc_act._run_brew("stop", "redis")
    assert ok is False
    assert "nope" in msg


def test_run_brew_handles_oserror(monkeypatch):
    def bad(*_a, **_kw):
        raise OSError("no brew")

    monkeypatch.setattr(svc_act.subprocess, "run", bad)
    ok, msg = svc_act._run_brew("start", "redis")
    assert ok is False
    assert "brew error" in msg


def test_run_brew_timeout(monkeypatch):
    def slow(*_a, **_kw):
        raise subprocess.TimeoutExpired(cmd="brew", timeout=1)

    monkeypatch.setattr(svc_act.subprocess, "run", slow)
    ok, msg = svc_act._run_brew("stop", "redis")
    assert ok is False


def test_terminate_pid_nonexistent():
    ok, msg = svc_act._terminate_pid(999_999_999)
    assert ok is True
    assert "gone" in msg


@pytest.mark.parametrize("action", ["start", "stop"])
def test_actions_are_labeled_correctly(monkeypatch, action):
    monkeypatch.setattr(svc_act, "_brew_available", lambda: False)
    svc = _svc(pid=None, brew_managed=False, brew_status=None)
    func = getattr(svc_act, action)
    out = func(svc, dry_run=True)
    assert out.action == action

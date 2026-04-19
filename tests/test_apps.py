"""Tests for cooldown.collectors.apps and cooldown.actions.apps."""
from __future__ import annotations

import os
import signal

import pytest

from cooldown.actions import apps as app_act
from cooldown.collectors import apps as apps_mod


def _app(kind: str = "wechat", pid: int = 4242, display: str = "WeChat") -> apps_mod.AppInfo:
    return apps_mod.AppInfo(
        kind=kind,
        app_name=display,
        display_name=display,
        pid=pid,
        rss=500 * 1024 * 1024,
        cpu_percent=0.1,
        ppid=1,
        frozen=False,
    )


# --- classifier ---------------------------------------------------------


def test_classify_main_wechat():
    result = apps_mod._classify(
        "WeChat",
        "/Applications/WeChat.app/Contents/MacOS/WeChat",
    )
    assert result == ("wechat", "WeChat")


def test_classify_skips_helpers():
    assert (
        apps_mod._classify(
            "WeChat Helper (Renderer)",
            "/Applications/WeChat.app/Contents/Frameworks/WeChat Helper.app/Contents/MacOS/WeChat Helper --type=renderer",
        )
        is None
    )


def test_classify_skips_gpu_helper():
    assert (
        apps_mod._classify(
            "Slack Helper (GPU)",
            "/Applications/Slack.app/Contents/Frameworks/Slack Helper (GPU).app/Contents/MacOS/Slack Helper (GPU) --type=gpu-process",
        )
        is None
    )


def test_classify_todesk_service_name_only():
    # ToDesk_Service often runs as a LaunchDaemon — we still pick it up.
    result = apps_mod._classify("todesk_service", "/Library/Application Support/ToDesk/todesk_service")
    assert result == ("todesk", "ToDesk")


def test_classify_unknown_returns_none():
    assert apps_mod._classify("firefox", "/Applications/Firefox.app/Contents/MacOS/firefox") is None


def test_is_helper_flags_type_arg():
    assert apps_mod._is_helper("X", "/x --type=utility") is True
    assert apps_mod._is_helper("X", "/x plain") is False


# --- actions ------------------------------------------------------------


def test_suspend_dry_run_no_signals(monkeypatch):
    def boom(*_a, **_kw):
        raise AssertionError("must not signal in dry-run")

    monkeypatch.setattr(app_act, "_signal_tree", boom)
    out = app_act.suspend(_app(), dry_run=True)
    assert out.ok is True
    assert "dry-run" in out.message
    assert out.action == "suspend"


def test_resume_dry_run_no_signals(monkeypatch):
    def boom(*_a, **_kw):
        raise AssertionError("must not signal in dry-run")

    monkeypatch.setattr(app_act, "_signal_tree", boom)
    out = app_act.resume(_app(), dry_run=True)
    assert out.ok is True
    assert "dry-run" in out.message
    assert out.action == "resume"


def test_quit_dry_run_no_osascript(monkeypatch):
    def boom(*_a, **_kw):
        raise AssertionError("must not call osascript in dry-run")

    monkeypatch.setattr(app_act, "_osascript_quit", boom)
    out = app_act.quit_app(_app(), dry_run=True)
    assert out.ok is True
    assert "dry-run" in out.message
    assert out.action == "quit"


def test_suspend_self_protection(monkeypatch):
    me = os.getpid()

    class FakeProc:
        def __init__(self, pid):
            self.pid = pid

        def children(self, recursive=False):
            return []

        def send_signal(self, _sig):
            raise AssertionError(f"must not signal protected pid={self.pid}")

    def fake_tree(pid):
        return [FakeProc(pid)]

    monkeypatch.setattr(app_act, "_process_tree", fake_tree)
    out = app_act.suspend(_app(pid=me), dry_run=False)
    # self-protection → nothing sent, so ok should be False
    assert out.ok is False
    assert "0 pid(s)" in out.message or "failed" in out.message


def test_signal_tree_counts_sent(monkeypatch):
    sent_signals: list[tuple[int, int]] = []

    class FakeProc:
        def __init__(self, pid):
            self.pid = pid

        def send_signal(self, sig):
            sent_signals.append((self.pid, int(sig)))

    def fake_tree(_pid):
        return [FakeProc(1111), FakeProc(2222)]

    monkeypatch.setattr(app_act, "_process_tree", fake_tree)
    monkeypatch.setattr(app_act, "_self_pid_chain", lambda: set())
    sent, failed, errs = app_act._signal_tree(1111, signal.SIGSTOP)
    assert sent == 2
    assert failed == 0
    assert errs == []
    assert {pid for pid, _ in sent_signals} == {1111, 2222}


def test_quit_app_self_protection(monkeypatch):
    me = os.getpid()

    def boom(*_a, **_kw):
        raise AssertionError("must not call osascript for self")

    monkeypatch.setattr(app_act, "_osascript_quit", boom)
    out = app_act.quit_app(_app(pid=me), dry_run=False)
    assert out.ok is False
    assert "protected" in out.message


def test_osascript_quit_failure(monkeypatch):
    class FakeProc:
        returncode = 1
        stdout = ""
        stderr = "execution error"

    monkeypatch.setattr(app_act.subprocess, "run", lambda *a, **kw: FakeProc())
    ok, msg = app_act._osascript_quit("WeChat")
    assert ok is False
    assert "execution error" in msg


@pytest.mark.parametrize("fn_name", ["suspend", "resume"])
def test_action_labels(monkeypatch, fn_name):
    monkeypatch.setattr(app_act, "_signal_tree", lambda *_a, **_kw: (1, 0, []))
    func = getattr(app_act, fn_name)
    out = func(_app(), dry_run=False)
    assert out.action == fn_name
    assert out.ok is True

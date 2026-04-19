"""Regression tests: collectors must swallow the full PROC_ERRORS family.

macOS' sysctl(KERN_PROCARGS2) can EPERM on protected processes; psutil
then surfaces that as PermissionError / OSError / SystemError instead of
its usual AccessDenied. Before 2026-04-19 this killed `cool watch` after
a few ticks. These tests pin the unified error tuple and simulate the
failure modes for every collector that walks process lists.
"""
from __future__ import annotations

from unittest.mock import MagicMock

import psutil
import pytest

from cooldown.collectors import (
    ancestry,
    apps,
    dev,
    procs,
    project,
    services,
)
from cooldown.util import PROC_ERRORS


def test_proc_errors_contains_all_known_suspects():
    assert psutil.NoSuchProcess in PROC_ERRORS
    assert psutil.AccessDenied in PROC_ERRORS
    assert psutil.ZombieProcess in PROC_ERRORS
    assert PermissionError in PROC_ERRORS
    assert OSError in PROC_ERRORS
    assert SystemError in PROC_ERRORS


class _FakeProc:
    """A psutil.Process-shaped mock that can be configured to raise
    arbitrary exceptions from each attribute accessor."""

    def __init__(
        self,
        pid: int,
        *,
        name: str = "node",
        cmdline_exc: type[BaseException] | None = None,
        info: dict | None = None,
    ) -> None:
        self.pid = pid
        self._name = name
        self._cmdline_exc = cmdline_exc
        self.info = info or {"pid": pid, "name": name}

    def name(self) -> str:
        return self._name

    def cmdline(self) -> list[str]:
        if self._cmdline_exc is not None:
            raise self._cmdline_exc("simulated KERN_PROCARGS2 EPERM")
        return [self._name]

    def cpu_percent(self, _interval):
        return 0.0

    def memory_info(self) -> MagicMock:  # .rss
        m = MagicMock()
        m.rss = 1024
        return m

    def ppid(self) -> int:
        return 1

    def username(self) -> str:
        return "me"

    def create_time(self) -> float:
        return 0.0

    def terminal(self) -> None:
        return None

    def oneshot(self):
        class _Ctx:
            def __enter__(self_inner):
                return self_inner
            def __exit__(self_inner, *_a):
                return False
        return _Ctx()


@pytest.mark.parametrize(
    "exc_cls",
    [SystemError, PermissionError, OSError, psutil.AccessDenied, psutil.NoSuchProcess],
)
def test_procs_collect_survives_cmdline_exception(monkeypatch, exc_cls):
    def fake_iter(_attrs):
        yield _FakeProc(1, name="node", cmdline_exc=exc_cls)
        yield _FakeProc(2, name="droid", cmdline_exc=None)

    monkeypatch.setattr(psutil, "process_iter", fake_iter)
    # Shrink sleep so the test is fast.
    result = procs.collect(sample_interval=0.0)
    # We just need it to not raise. Droid candidate may or may not survive
    # depending on cpu sampling; the point is no exception escapes.
    assert isinstance(result, list)


@pytest.mark.parametrize("exc_cls", [SystemError, PermissionError, OSError])
def test_dev_collect_survives_cmdline_exception(monkeypatch, exc_cls):
    def fake_iter(_attrs):
        yield _FakeProc(1, name="node", cmdline_exc=exc_cls)

    monkeypatch.setattr(psutil, "process_iter", fake_iter)
    monkeypatch.setattr(dev.project_mod, "get_cwd", lambda _pid: None)
    monkeypatch.setattr(dev.project_mod, "find_root", lambda _cwd: None)
    monkeypatch.setattr(
        dev.ancestry_mod,
        "find_launcher",
        lambda _pid: ancestry.Launcher(kind="unknown", label="unknown", pid=None),
    )
    out = dev.collect(sample_interval=0.0)
    assert isinstance(out, list)


@pytest.mark.parametrize("exc_cls", [SystemError, PermissionError, OSError])
def test_apps_collect_survives_cmdline_exception(monkeypatch, exc_cls):
    def fake_iter(_attrs):
        yield _FakeProc(1, name="WeChat", cmdline_exc=exc_cls)

    monkeypatch.setattr(psutil, "process_iter", fake_iter)
    out = apps.collect(freeze_sample_interval=0.0)
    assert isinstance(out, list)


@pytest.mark.parametrize("exc_cls", [SystemError, PermissionError, OSError])
def test_services_scan_survives_cmdline_exception(monkeypatch, exc_cls):
    def fake_iter(_attrs):
        yield _FakeProc(1, name="postgres", cmdline_exc=exc_cls)

    monkeypatch.setattr(psutil, "process_iter", fake_iter)
    groups = services._scan_processes()
    assert isinstance(groups, dict)


@pytest.mark.parametrize("exc_cls", [SystemError, PermissionError, OSError])
def test_ancestry_inspect_survives_all(monkeypatch, exc_cls):
    proc = MagicMock()
    proc.name.side_effect = exc_cls("boom")
    proc.exe.side_effect = exc_cls("boom")
    proc.cmdline.side_effect = exc_cls("boom")
    proc.ppid.side_effect = exc_cls("boom")
    name, exe, cmd, ppid = ancestry._safe_fields(proc)
    assert name == ""
    assert exe == ""
    assert cmd == ""
    assert ppid == 0


@pytest.mark.parametrize("exc_cls", [SystemError, PermissionError, OSError])
def test_project_get_cwd_survives_all(monkeypatch, exc_cls):
    fake = MagicMock()
    fake.cwd.side_effect = exc_cls("boom")
    monkeypatch.setattr(project.psutil, "Process", lambda _pid: fake)
    monkeypatch.setattr(project, "_cwd_via_lsof", lambda _pid: None)
    assert project.get_cwd(1234) is None

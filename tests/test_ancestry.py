"""Unit tests for `cooldown.collectors.ancestry`.

We fabricate fake psutil.Process-like objects via ``mocker.Mock`` rather
than spawning real processes so the tests are deterministic across CI and
the author's workstation.
"""
from __future__ import annotations

from unittest.mock import Mock

import psutil
import pytest

from cooldown.collectors import ancestry as ancestry_mod
from cooldown.collectors.ancestry import Launcher, classify_ancestor, find_launcher


def _fake_proc(
    *,
    pid: int = 1000,
    name: str = "",
    exe: str = "",
    cmdline: list[str] | None = None,
    ppid: int = 100,
) -> Mock:
    p = Mock(spec=psutil.Process)
    p.pid = pid
    p.name.return_value = name
    p.exe.return_value = exe
    p.cmdline.return_value = cmdline or []
    p.ppid.return_value = ppid
    return p


def test_classify_tmux():
    p = _fake_proc(name="tmux", exe="/opt/homebrew/bin/tmux", cmdline=["tmux", "new", "-s", "a"])
    got = classify_ancestor(p)
    assert got is not None
    assert got.kind == "tmux"
    assert got.label == "tmux"
    assert got.pid == p.pid


def test_classify_cmux_zellij():
    assert classify_ancestor(_fake_proc(name="cmux", cmdline=["cmux"])).kind == "cmux"
    assert classify_ancestor(_fake_proc(name="zellij", cmdline=["zellij"])).kind == "zellij"


@pytest.mark.parametrize(
    "kind",
    ["droid", "codex", "claude", "opencode", "nanobot", "hermes"],
)
def test_classify_ai_clis(kind):
    p = _fake_proc(name=kind, cmdline=[f"/usr/local/bin/{kind}", "run"])
    got = classify_ancestor(p)
    assert got is not None, kind
    assert got.kind == kind


def test_classify_vscode_helper():
    p = _fake_proc(
        name="Code Helper",
        exe="/Applications/Visual Studio Code.app/Contents/Frameworks/Code Helper.app/Contents/MacOS/Code Helper",
    )
    got = classify_ancestor(p)
    assert got is not None
    assert got.kind == "vscode"


def test_classify_cursor():
    p = _fake_proc(
        name="Cursor",
        exe="/Applications/Cursor.app/Contents/MacOS/Cursor",
    )
    got = classify_ancestor(p)
    assert got is not None
    assert got.kind == "cursor"


def test_classify_datagrip():
    p = _fake_proc(name="datagrip", exe="/Applications/DataGrip.app/Contents/MacOS/datagrip")
    got = classify_ancestor(p)
    assert got is not None
    assert got.kind == "datagrip"


@pytest.mark.parametrize("tag", ["IntelliJ", "PyCharm", "WebStorm", "GoLand", "RubyMine", "CLion"])
def test_classify_jetbrains(tag):
    p = _fake_proc(name=tag.lower(), exe=f"/Applications/{tag} Ultimate.app/Contents/MacOS/{tag.lower()}")
    got = classify_ancestor(p)
    assert got is not None
    assert got.kind == "jetbrains"


@pytest.mark.parametrize(
    "bundle,expected",
    [
        ("Warp", "warp"),
        ("Ghostty", "ghostty"),
        ("Alacritty", "alacritty"),
        ("WezTerm", "wezterm"),
        ("kitty", "kitty"),
        ("iTerm", "iterm"),
        ("iTerm2", "iterm"),  # prefix match
        ("Terminal", "terminal"),
        ("Kaku", "kaku"),
    ],
)
def test_classify_terminals(bundle, expected):
    p = _fake_proc(
        name=bundle.lower(),
        exe=f"/Applications/{bundle}.app/Contents/MacOS/{bundle}",
    )
    got = classify_ancestor(p)
    assert got is not None, bundle
    assert got.kind == expected


def test_classify_launchd_only_when_pid1():
    p = _fake_proc(pid=1, name="launchd", ppid=0)
    got = classify_ancestor(p)
    assert got is not None
    assert got.kind == "launchd"


def test_classify_finder():
    p = _fake_proc(name="Finder", exe="/System/Library/CoreServices/Finder.app/Contents/MacOS/Finder")
    got = classify_ancestor(p)
    assert got is not None
    assert got.kind == "finder"


def test_classify_shell_marks_but_does_not_stop():
    p = _fake_proc(name="zsh", exe="/bin/zsh", cmdline=["-zsh"])
    got = classify_ancestor(p)
    assert got is not None
    assert got.kind == "shell"


def test_classify_unknown_returns_none():
    p = _fake_proc(name="blargle", exe="/opt/homebrew/bin/blargle", cmdline=["blargle"])
    assert classify_ancestor(p) is None


def test_find_launcher_skips_shells(mocker):
    shell = _fake_proc(pid=200, name="zsh", exe="/bin/zsh", cmdline=["-zsh"], ppid=100)
    tmux = _fake_proc(pid=100, name="tmux", exe="/opt/homebrew/bin/tmux", cmdline=["tmux"], ppid=50)
    launchd = _fake_proc(pid=50, name="launchd", ppid=0)

    target = _fake_proc(pid=999, name="node", cmdline=["node"], ppid=200)
    mocker.patch.object(ancestry_mod, "walk", return_value=[shell, tmux, launchd])
    mocker.patch.object(psutil, "Process", return_value=target)

    got = find_launcher(999)
    assert got.kind == "tmux"
    assert got.pid == 100


def test_find_launcher_orphan(mocker):
    target = _fake_proc(pid=999, ppid=1)
    mocker.patch.object(ancestry_mod, "walk", return_value=[])
    mocker.patch.object(psutil, "Process", return_value=target)
    got = find_launcher(999)
    assert got == Launcher(kind="launchd", label="launchd (orphan)", pid=1)


def test_find_launcher_unknown(mocker):
    target = _fake_proc(pid=999, ppid=42)
    mocker.patch.object(ancestry_mod, "walk", return_value=[])
    mocker.patch.object(psutil, "Process", return_value=target)
    got = find_launcher(999)
    assert got.kind == "unknown"
    assert got.pid is None


def test_find_launcher_swallows_errors(mocker):
    mocker.patch.object(psutil, "Process", side_effect=psutil.NoSuchProcess(pid=1))
    got = find_launcher(12345)
    assert got.kind == "unknown"

"""Unit tests for `cooldown.collectors.dev`."""
from __future__ import annotations

import time
from pathlib import Path

from cooldown.collectors import dev as dev_mod
from cooldown.collectors.ancestry import Launcher
from cooldown.collectors.dev import DevProc
from cooldown.collectors.project import Project


def _mk(
    pid: int,
    *,
    lang: str = "node",
    rss: int = 100,
    cpu: float = 0.0,
    ppid: int = 100,
    framework: str | None = None,
    project: Project | None = None,
    launcher: Launcher | None = None,
    is_orphan: bool = False,
    idle: float | None = None,
) -> DevProc:
    return DevProc(
        pid=pid,
        ppid=ppid,
        lang=lang,
        framework=framework,
        name=lang,
        cmdline=f"{lang} --run",
        rss=rss,
        cpu_percent=cpu,
        age=0.0,
        cwd=None,
        project=project,
        launcher=launcher or Launcher(kind="unknown", label="unknown", pid=None),
        is_orphan=is_orphan,
        user="me",
        idle_seconds=idle,
    )


def test_collect_returns_list_no_crash():
    # Minimal smoke test — we only assert it returns a list and no raised
    # exceptions. On CI the list may be empty.
    result = dev_mod.collect(sample_interval=0.05)
    assert isinstance(result, list)
    for d in result:
        assert isinstance(d, DevProc)
        assert d.lang in {
            "node", "python", "ruby", "go", "rust", "java", "php", "deno", "bun", "dotnet",
        }


def test_group_by_project_sorts_by_rss(tmp_path: Path):
    proj_a = Project(root=tmp_path / "a", name="alpha", markers=["package.json"])
    proj_b = Project(root=tmp_path / "b", name="beta", markers=["pyproject.toml"])
    devs = [
        _mk(1, rss=100, project=proj_a),
        _mk(2, rss=500, project=proj_b),
        _mk(3, rss=400, project=proj_b),
        _mk(4, rss=50, project=None),
    ]
    groups = dev_mod.group_by(devs, "project")
    order = list(groups.keys())
    # beta has 900 total, alpha 100, unknown 50 → beta first.
    assert order[0] == "beta"
    assert order[-1] == "(cwd unknown)"
    # Inside beta, order by -rss
    assert [d.pid for d in groups["beta"]] == [2, 3]


def test_group_by_lang():
    devs = [
        _mk(1, lang="node", rss=100),
        _mk(2, lang="python", rss=500),
        _mk(3, lang="python", rss=100),
    ]
    groups = dev_mod.group_by(devs, "lang")
    order = list(groups.keys())
    assert order[0] == "python"
    assert order[1] == "node"


def test_group_by_launcher_framework():
    launcher = Launcher(kind="tmux", label="tmux", pid=10)
    devs = [
        _mk(1, lang="node", framework="vite", launcher=launcher, rss=300),
        _mk(2, lang="python", framework=None, launcher=launcher, rss=200),
    ]
    by_launcher = dev_mod.group_by(devs, "launcher")
    assert list(by_launcher.keys()) == ["tmux"]

    by_fw = dev_mod.group_by(devs, "framework")
    assert "vite" in by_fw
    assert "(none)" in by_fw


def test_stale_requires_orphan_or_old_project(tmp_path: Path):
    # Make a fresh project root. mtime is recent, so project alone
    # shouldn't qualify.
    root = tmp_path / "fresh"
    root.mkdir()
    fresh_proj = Project(root=root, name="fresh", markers=["package.json"])
    fresh_dev = _mk(1, project=fresh_proj, cpu=0.0, idle=3600)
    assert dev_mod.stale([fresh_dev]) == []

    # Orphan + low cpu + high idle → stale.
    orphan = _mk(2, ppid=1, is_orphan=True, cpu=0.0, idle=3600)
    assert dev_mod.stale([orphan]) == [orphan]

    # Orphan but busy → not stale.
    busy = _mk(3, ppid=1, is_orphan=True, cpu=5.0, idle=3600)
    assert dev_mod.stale([busy]) == []

    # Orphan + low cpu + low idle → not stale.
    active = _mk(4, ppid=1, is_orphan=True, cpu=0.0, idle=60)
    assert dev_mod.stale([active]) == []


def test_stale_old_project_counts_as_aged(tmp_path: Path, mocker):
    root = tmp_path / "old"
    root.mkdir()
    # Force the project root to look ancient.
    ancient = time.time() - 30 * 86400
    mocker.patch("pathlib.Path.stat", return_value=type("S", (), {"st_mtime": ancient})())
    proj = Project(root=root, name="old", markers=["package.json"])
    dev = _mk(1, project=proj, ppid=200, is_orphan=False, cpu=0.0, idle=3600)
    assert dev_mod.stale([dev]) == [dev]


def test_enrich_idle_sets_value():
    devs = [_mk(1, rss=100)]
    devs[0].age = 120.0
    dev_mod.enrich_idle(devs)
    assert devs[0].idle_seconds is not None
    assert devs[0].idle_seconds >= 0


def test_classify_lang_and_framework():
    assert dev_mod._classify_lang("node", "/usr/bin/node vite") == "node"
    assert dev_mod._classify_lang("python3", "/usr/bin/python3 -m uvicorn app:app") == "python"
    # Only python gets uvicorn attribution.
    assert dev_mod._classify_framework("python", "uvicorn app:app") == "uvicorn"
    assert dev_mod._classify_framework("node", "uvicorn app:app") is None
    assert dev_mod._classify_framework("node", "/path/to/next-server main") == "next"


def test_is_self_excludes_cool_cli():
    assert dev_mod._is_self("python3", "python3 -m cooldown.cli dev")
    assert dev_mod._is_self("cool", "/Users/x/.venv/bin/cool dev")
    assert not dev_mod._is_self("node", "node server.js")

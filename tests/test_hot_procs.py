"""Unit tests for the ``hot_procs`` collector and its dashboard panel."""
from __future__ import annotations

import json as _json
from io import StringIO
from unittest.mock import MagicMock, patch

from rich.console import Console

from cooldown.collectors import hot_procs as hot_mod
from cooldown.ui import dashboard


class FakeProc:
    """Stand-in for psutil.Process. ``cpu_percent`` returns the primed
    value on the second call (matches psutil's two-pass behaviour)."""

    def __init__(self, pid: int, *, cpu: float, rss: int, name: str = "py",
                 cmdline: str | None = None, user: str = "u",
                 create_time: float = 0.0):
        self.pid = pid
        self._cpu = cpu
        self._rss = rss
        self._name = name
        self._cmdline = cmdline or [name]
        self._user = user
        self._create_time = create_time
        self._primed = False

    def cpu_percent(self, interval=None):
        if not self._primed:
            self._primed = True
            return 0.0
        return self._cpu

    def oneshot(self):
        class _Ctx:
            def __enter__(self):  # noqa: PLR0204 — psutil oneshot protocol
                return self
            def __exit__(self, *_a):
                return False
        return _Ctx()

    def memory_info(self):
        m = MagicMock()
        m.rss = self._rss
        return m

    def create_time(self):
        return self._create_time

    def username(self):
        return self._user

    def name(self):
        return self._name

    def cmdline(self):
        return list(self._cmdline)


def test_collect_returns_top_n_sorted_descending(monkeypatch):
    """The collector must return at most ``top_n`` rows, sorted by CPU%
    descending — that's the whole point of the panel."""
    fakes = [
        FakeProc(101, cpu=300.0, rss=100_000_000, name="hot1"),
        FakeProc(102, cpu=10.0, rss=20_000_000, name="cool"),
        FakeProc(103, cpu=900.0, rss=50_000_000, name="hottest"),
        FakeProc(104, cpu=0.0, rss=1_000, name="zero"),       # filtered out
        FakeProc(105, cpu=150.0, rss=30_000_000, name="mid"),
    ]
    monkeypatch.setattr(hot_mod.psutil, "process_iter", lambda attrs=None: iter(fakes))
    monkeypatch.setattr(hot_mod.psutil, "cpu_count", lambda logical=True: 10)
    monkeypatch.setattr(hot_mod.time, "sleep", lambda _: None)

    rows = hot_mod.collect(top_n=3, sample_interval=0.0)

    assert [r.pid for r in rows] == [103, 101, 105]
    # cpu_percent is normalized: 900 raw / 10 cpus = 90.0
    assert rows[0].cpu_percent == 90.0
    assert rows[1].cpu_percent == 30.0


def test_collect_skips_zero_cpu_processes(monkeypatch):
    """A 0% process must not occupy a slot in TOP-N — otherwise an idle
    system would always fill the panel with noise."""
    fakes = [
        FakeProc(1, cpu=0.0, rss=1, name="a"),
        FakeProc(2, cpu=0.0, rss=1, name="b"),
        FakeProc(3, cpu=50.0, rss=1, name="c"),
    ]
    monkeypatch.setattr(hot_mod.psutil, "process_iter", lambda attrs=None: iter(fakes))
    monkeypatch.setattr(hot_mod.psutil, "cpu_count", lambda logical=True: 10)
    monkeypatch.setattr(hot_mod.time, "sleep", lambda _: None)

    rows = hot_mod.collect(top_n=5, sample_interval=0.0)

    assert len(rows) == 1
    assert rows[0].pid == 3


def test_collect_survives_process_errors(monkeypatch):
    """A NoSuchProcess / AccessDenied mid-iteration must not abort the
    whole sweep — the panel still has to render for surviving procs."""
    class Boom:
        pid = 999
        def cpu_percent(self, interval=None):
            raise hot_mod.psutil.NoSuchProcess(999)

    good = FakeProc(7, cpu=42.0, rss=1, name="ok")
    monkeypatch.setattr(
        hot_mod.psutil, "process_iter", lambda attrs=None: iter([Boom(), good])
    )
    monkeypatch.setattr(hot_mod.psutil, "cpu_count", lambda logical=True: 10)
    monkeypatch.setattr(hot_mod.time, "sleep", lambda _: None)

    rows = hot_mod.collect(top_n=5, sample_interval=0.0)
    assert [r.pid for r in rows] == [7]


def test_shorten_cmd_strips_interpreter_but_keeps_script_path(monkeypatch):
    """Interpreter prefix collapses to its basename (`Python`), but the
    script path keeps enough segments to identify the project — otherwise
    three `python script.py` rows in different projects all look the same."""
    monkeypatch.setenv("HOME", "/Users/me")
    cmd = "/opt/homebrew/Cellar/python@3.14/3.14.4/.../Python /Users/me/.hermes/scripts/doctor.py --flag value"
    out = dashboard.shorten_cmd("Python", cmd, width=80)
    assert out.startswith("Python ")
    # HOME collapsed to ~
    assert "~/.hermes/scripts/doctor.py" in out
    assert "/Users/me/" not in out
    # Interpreter front-matter dropped to its basename
    assert "/Cellar/" not in out


def test_shorten_cmd_disambiguates_same_basename(monkeypatch):
    """The Hot Processes panel must let three `Python script.py` from
    different project dirs render distinguishably. The old basename-only
    strategy made them identical, which was the bug that motivated this."""
    monkeypatch.setenv("HOME", "/Users/me")
    a = dashboard.shorten_cmd("Python", "/usr/bin/python /Users/me/projects/foo/script.py", width=60)
    b = dashboard.shorten_cmd("Python", "/usr/bin/python /Users/me/projects/bar/script.py", width=60)
    c = dashboard.shorten_cmd("Python", "/usr/bin/python /Users/me/projects/baz/script.py", width=60)
    assert a != b != c, f"rows must differ: a={a!r} b={b!r} c={c!r}"
    assert "foo" in a and "bar" in b and "baz" in c


def test_shorten_cmd_truncates_long_paths_from_the_middle(monkeypatch):
    """When the path is too long for the budget, keep the script tail
    (parent dir + filename), drop the head with `…/`. The tail is what
    disambiguates rows; the head usually doesn't."""
    monkeypatch.setenv("HOME", "/Users/me")
    cmd = "python /Users/me/a/b/c/d/e/f/g/h/i/long_named_script.py --flag value"
    out = dashboard.shorten_cmd("python", cmd, width=40)
    assert len(out) <= 40
    # Script name and at least its parent dir survive — they identify the row.
    assert "long_named_script.py" in out
    assert out.startswith("python ")


def test_shorten_cmd_within_budget_returns_intact(monkeypatch):
    """Short commands must pass through untouched — no spurious …/ noise
    on a `Python` or `cmux` row that's already minimal."""
    monkeypatch.setenv("HOME", "/Users/me")
    assert dashboard.shorten_cmd("cmux", "cmux") == "cmux"
    assert dashboard.shorten_cmd("python", "python -V") == "python -V"


def test_shorten_cmd_handles_empty_cmdline():
    """When cmdline is empty (kernel threads, defunct procs), fall back
    to the process name rather than rendering blank rows."""
    assert dashboard.shorten_cmd("kernel_task", "") == "kernel_task"
    assert dashboard.shorten_cmd("", "") == "?"


def test_compact_path_collapses_home():
    """Direct unit test on the helper — exact substitution rules."""
    p = dashboard._compact_path("/Users/me/x/y.py", home="/Users/me")
    assert p == "~/x/y.py"
    # Different home → no rewrite
    p2 = dashboard._compact_path("/Users/other/x/y.py", home="/Users/me")
    assert p2 == "/Users/other/x/y.py"
    # Exactly the home dir
    assert dashboard._compact_path("/Users/me", home="/Users/me") == "~"


def test_shorten_path_token_keeps_tail():
    """The path-token shortener must always preserve the last two segments
    (filename + parent dir) even under aggressive budget pressure."""
    out = dashboard._shorten_path_token("/a/b/c/d/e/f.py", 12)
    assert out.endswith("e/f.py"), f"unexpected: {out!r}"
    assert out.startswith("…/")
    # Short paths pass through
    assert dashboard._shorten_path_token("script.py", 80) == "script.py"


def test_group_key_collapses_app_bundle():
    """The .app bundle name is the grouping key (collapses Chrome's helper
    fleet); leftmost bundle wins for nested helpers; non-.app falls back to
    the process name."""
    assert hot_mod.group_key(
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome", "", "Google Chrome"
    ) == "Google Chrome"
    assert hot_mod.group_key(
        "", "/Applications/Visual Studio Code.app/x/Code Helper.app/y", "Code Helper"
    ) == "Visual Studio Code"
    assert hot_mod.group_key("", "", "python3.13") == "python3.13"


def test_aggregate_by_app_cores_and_coverage():
    """``cores`` is Σraw/100 and ``pct_sys`` is Σ(normalized); the tail the
    cut hides is reported so the panel can stay honest."""
    procs = [
        hot_mod.HotProc(
            pid=i, name="Google Chrome", cmdline="x", cpu_percent=5.0, rss=10,
            user="u", create_time=0.0, age=1.0,
            exe="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        )
        for i in range(3)
    ]
    procs.append(
        hot_mod.HotProc(
            pid=99, name="node", cmdline="node x", cpu_percent=2.0, rss=5,
            user="u", create_time=0.0, age=1.0, exe="/usr/bin/node",
        )
    )
    apps, cov = hot_mod.aggregate_by_app(procs, ncpu=10, top_n=1)
    assert apps[0].app == "Google Chrome"
    assert apps[0].nproc == 3
    assert abs(apps[0].cores - 1.5) < 1e-9  # 15% * 10 / 100
    assert abs(apps[0].pct_sys - 15.0) < 1e-9
    # top_n=1 pushes node into the hidden tail.
    assert cov.tail_nproc == 1
    assert abs(cov.tail_pct_sys - 2.0) < 1e-9
    assert abs(cov.total_pct_sys - 17.0) < 1e-9


def test_hot_apps_content_handles_empty():
    """Empty groups must render a friendly empty-state row, not crash."""
    tbl = dashboard.hot_apps_content([])
    assert tbl.row_count == 1


def test_hot_apps_content_paints_runaway_red():
    """A group eating >= 0.8 cores must render the cores cell bold-red — the
    whole reason the panel exists is to make runaways visually obvious."""
    proc = hot_mod.HotProc(
        pid=42, name="py", cmdline="python doctor.py",
        cpu_percent=9.5,  # 9.5% of a 10-core box = 0.95 cores
        rss=1_000_000, user="u", create_time=0.0, age=10.0,
    )
    apps, _ = hot_mod.aggregate_by_app([proc], ncpu=10, top_n=8)
    tbl = dashboard.hot_apps_content(apps)
    from io import StringIO

    from rich.console import Console
    buf = StringIO()
    Console(file=buf, force_terminal=True, color_system="truecolor", width=200).print(tbl)
    rendered = buf.getvalue()
    # The group renders with its %sys share and the runaway cores cell is
    # painted bold-red (ANSI SGR 1;31) — we don't pin exact bytes, just that
    # red is emitted for a >= 0.8-core group.
    assert "9.5" in rendered
    assert "py" in rendered
    assert "\x1b[1;31m" in rendered


def test_render_json_includes_hot_procs():
    """``cool status --json`` must expose hot_procs so scripts can act
    on the same data the panel renders."""
    with patch.object(hot_mod, "collect", return_value=[
        hot_mod.HotProc(pid=1, name="py", cmdline="py x.py",
                        cpu_percent=80.0, rss=1, user="u",
                        create_time=0.0, age=1.0),
    ]):
        buf = StringIO()
        dashboard.render_json(Console(file=buf, width=200))
    payload = _json.loads(buf.getvalue())
    assert "hot_procs" in payload
    assert payload["hot_procs"][0]["pid"] == 1
    assert payload["hot_procs"][0]["cpu_percent"] == 80.0

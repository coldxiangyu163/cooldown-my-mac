"""Smoke tests for the Textual-backed `cool watch` dashboard.

Skips entirely when the optional ``textual`` dependency is not installed.
"""
from __future__ import annotations

import pytest

pytest.importorskip("textual")

from cooldown.collectors.project import Project  # noqa: E402
from cooldown.ui import watch  # noqa: E402


def _binding_keys(bindings) -> set[str]:
    """Return the set of keys declared in a Textual ``BINDINGS`` list.

    ``BINDINGS`` may contain either tuples ``(key, action, description)`` or
    ``textual.binding.Binding`` instances. Compound keys like ``"plus,equals"``
    are split so each individual key is checked.
    """
    keys: set[str] = set()
    for b in bindings:
        raw = b[0] if isinstance(b, tuple) else getattr(b, "key", "")
        for chunk in str(raw).split(","):
            chunk = chunk.strip()
            if chunk:
                keys.add(chunk)
    return keys


def test_watch_module_does_not_import_textual_eagerly():
    # Simply importing the module must succeed without textual being loaded
    # as a side-effect of cooldown.ui.watch itself — the module does a lazy
    # import inside ``_build_app_class`` / ``run``.
    import importlib

    mod = importlib.import_module("cooldown.ui.watch")
    # textual is present in this test env (importorskip above), but the
    # watch module must not re-export it or bind it at module scope.
    assert not hasattr(mod, "App")
    assert not hasattr(mod, "Static")


def test_watch_app_has_required_bindings():
    app_cls = watch._build_app_class()
    keys = _binding_keys(app_cls.BINDINGS)
    # Quit / pause / refresh are the non-negotiable UX minimum.
    for expected in ("q", "r", "p"):
        assert expected in keys, f"missing binding: {expected!r} (have {keys})"
    # New dashboard adds slow refresh, dry-run, kill, focus shortcuts.
    for expected in ("R", "d", "k", "K", "1", "2", "3"):
        assert expected in keys, f"missing binding: {expected!r} (have {keys})"


def test_watch_kill_toasts_make_dry_run_explicit():
    msg, severity = watch.kill_start_message(dry_run=True, force=False, pids=1)
    assert severity == "information"
    assert "DRY-RUN" in msg
    assert "no process killed" in msg
    assert "press d for LIVE" in msg

    done, done_severity = watch.kill_done_message(dry_run=True, ok=1, failed=0)
    assert done_severity == "information"
    assert "0 killed" in done


def test_watch_live_kill_toasts_report_real_action():
    msg, severity = watch.kill_start_message(dry_run=False, force=False, pids=2)
    assert msg == "SIGTERM 2 pid(s)…"
    assert severity == "warning"

    done, done_severity = watch.kill_done_message(dry_run=False, ok=1, failed=1)
    assert done == "1 killed · 1 failed"
    assert done_severity == "warning"


def test_watch_kill_toast_surfaces_worker_breakdown():
    """When a folded reloader row signals more PIDs than rows selected,
    the toast must spell out the breakdown so the count isn't a
    surprise to the user."""
    dry, _ = watch.kill_start_message(
        dry_run=True, force=False, pids=2, workers=1
    )
    assert "DRY-RUN 2 pid(s) (1 + 1 worker)" in dry

    live, _ = watch.kill_start_message(
        dry_run=False, force=True, pids=3, workers=2
    )
    assert live == "SIGKILL 3 pid(s) (1 + 2 workers)…"


def test_watch_app_compose_contains_healthbar_body_footer():
    app_cls = watch._build_app_class()
    app = app_cls(fast_interval=3, slow_interval=15)
    widgets = list(app.compose())
    # The default Textual Header was removed so the custom healthbar
    # can be the sole designed top strip (clock folded into it). Three
    # top-level widgets: healthbar Static + Grid(body) + Footer.
    assert len(widgets) == 3, f"expected 3 top-level widgets, got {len(widgets)}"
    ids = [getattr(w, "id", None) for w in widgets]
    assert "healthbar" in ids
    assert "body" in ids


def test_watch_app_title_and_default_intervals():
    app_cls = watch._build_app_class()
    app = app_cls()
    assert app.fast_interval == 3
    assert app.slow_interval == 15
    assert app.TITLE == "cooldown · watch"
    assert app.paused is False
    assert app.dry_run is False


def test_run_without_textual_prints_hint(monkeypatch):
    """When textual cannot be imported, ``run`` must return non-zero and
    print a clear install hint rather than raising."""
    from rich.console import Console

    def _raise(*_a, **_kw):
        raise ImportError("textual missing (simulated)")

    monkeypatch.setattr(watch, "_build_app_class", _raise)

    buf_console = Console(record=True, width=100)
    rc = watch.run(buf_console, interval=3, slow_interval=15)
    assert rc != 0
    output = buf_console.export_text()
    assert "textual is not installed" in output
    assert "pip install textual" in output or "pipx inject" in output


# ---------------------------------------------------------------------------
# Pure row-builder tests (no textual required)
# ---------------------------------------------------------------------------

def test_build_ai_rows_groups_and_sums():
    from cooldown.collectors.procs import ProcInfo

    def _p(pid, kind, rss, cpu=0.0, idle=0.0):
        return ProcInfo(
            pid=pid, ppid=1, kind=kind, name=kind, cmdline=kind,
            rss=rss, cpu_percent=cpu, create_time=0.0, age=0.0,
            tty=None, user="me", idle_seconds=idle,
        )

    procs = [_p(1, "droid", 100), _p(2, "droid", 50), _p(3, "codex", 300)]
    rows = watch.build_ai_rows(procs)
    by_kind = {r.kind: r for r in rows}
    assert by_kind["droid"].count == 2
    assert by_kind["droid"].rss == 150
    assert set(by_kind["droid"].pids) == {1, 2}
    assert by_kind["codex"].count == 1


def test_build_project_rows_ranks_by_rss():
    from cooldown.collectors.ancestry import Launcher
    from cooldown.collectors.dev import DevProc

    def _d(pid, project, lang, rss, orphan=False):
        return DevProc(
            pid=pid, ppid=1, lang=lang, framework=None, name=lang,
            cmdline=lang, rss=rss, cpu_percent=0.0, age=0.0,
            cwd=None,
            project=None if project is None else Project(root=project, name=project, markers=[]),
            launcher=Launcher(kind="launchd", label="launchd", pid=1),
            is_orphan=orphan, user="me",
        )

    devs = [
        _d(1, "alpha", "node", 500),
        _d(2, "alpha", "python", 700),
        _d(3, "beta", "node", 200, orphan=True),
    ]
    rows = watch.build_project_rows(devs)
    # alpha (1.2GB) comes first.
    assert rows[0].name == "alpha"
    assert rows[0].rss == 1200
    assert rows[0].count == 2
    assert rows[0].orphan is False
    # beta's one orphan flags the whole row.
    beta = next(r for r in rows if r.name == "beta")
    assert beta.orphan is True


def test_build_port_rows_dedup_ipv4_ipv6_twins():
    from cooldown.collectors.ports import PortEntry

    e4 = PortEntry(port=5432, proto="tcp4", bind="127.0.0.1", pid=1000,
                   process="postgres", user="me")
    e6 = PortEntry(port=5432, proto="tcp6", bind="::1", pid=1000,
                   process="postgres", user="me")
    e_other = PortEntry(port=3306, proto="tcp4", bind="*", pid=2000,
                        process="mysqld", user="me")
    rows = watch.build_port_rows([e4, e6, e_other], {}, {})
    # Same (port, pid) collapsed to one row.
    assert len(rows) == 2
    ports_ = sorted(r.port for r in rows)
    assert ports_ == [3306, 5432]


def test_build_port_rows_carries_workers_through():
    """The ``workers_by_pid`` map must reach the rendered ``PortRow``
    so the table can display the ``+N worker`` chip."""
    from cooldown.collectors.ports import PortEntry

    parent = PortEntry(port=8000, proto="tcp4", bind="*", pid=19873,
                       process="python3.13", user="me")
    rows = watch.build_port_rows(
        [parent], {}, {}, workers_by_pid={19873: [31043]}
    )
    assert len(rows) == 1
    assert rows[0].pid == 19873
    assert rows[0].workers == [31043]


def test_render_subtitle_includes_all_bits():
    from cooldown.collectors.memory import MemoryStats

    mem = MemoryStats(
        total=64 * 1024**3, used=40 * 1024**3, available=20 * 1024**3,
        used_percent=62.5, wired=10 * 1024**3, compressed=5 * 1024**3,
        swap_total=10 * 1024**3, swap_used=1 * 1024**3,
        page_size=16384, pressure_level="warn",
    )
    sub = watch.render_subtitle(
        mem=mem, sys_stats=None, therm=None, procs=[],
        paused=False, dry_run=True,
    )
    assert "pressure" in sub
    assert "warn" in sub
    # Cadence (⟳ 3s/15s) was dropped from the healthbar — it's a static
    # config value, not live data. dry-run mode still surfaces because
    # it's a non-default operational state the user needs to see.
    assert "3s/15s" not in sub
    assert "dry-run" in sub


def test_render_subtitle_embeds_host_and_battery_when_provided():
    from cooldown.collectors.battery import BatteryStats
    from cooldown.collectors.hostinfo import HostInfo

    host = HostInfo(
        model="MacBook Pro",
        chip="Apple M1 Max",
        gpu_cores=32,
        perf_cores=8,
        eff_cores=2,
        ram_bytes=64 * 1024 ** 3,
        disk_total_bytes=2 * 1024 ** 4,
        macos_version="15.2",
    )
    batt = BatteryStats(
        percent=82.0, cycle_count=100, temp_c=41.5, health_percent=90.0,
        condition=None, charging=True, ac_attached=True, power_w=18.5,
        minutes_remaining=42, design_capacity_mah=6000,
        max_capacity_mah=5400, fully_charged=False,
    )
    sub = watch.render_subtitle(
        mem=None, sys_stats=None, therm=None, procs=None,
        paused=False, dry_run=False,
        host=host, battery=batt,
    )
    # Machine identity string appears.
    assert "MacBook Pro" in sub
    assert "M1 Max" in sub
    assert "32GPU" in sub
    assert "8P+2E" in sub
    # Identity zone uses the shared ``human_bytes`` formatter so units
    # stay consistent with the panel content (no more bespoke "64G").
    assert "64.0GB RAM" in sub
    assert "macOS 15.2" in sub
    # disk total + uptime were trimmed from identity to keep the bar
    # under typical terminal widths — they used to push the clock and
    # cadence off-screen. Pin their absence so the design intent
    # doesn't regress later.
    assert "disk" not in sub
    assert "up " not in sub
    # Hot-battery indicator is colored red (>=40°C triggers bold red).
    assert "41.5" in sub
    assert "bold red" in sub


# ---------------------------------------------------------------------------
# End-to-end: mount the app headlessly and push one fake tick through each
# apply handler. This catches layout / CSS / widget-id regressions that the
# pure-logic tests above miss.
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_watch_app_end_to_end_mount_and_apply():
    from cooldown.collectors.memory import MemoryStats
    from cooldown.collectors.procs import ProcInfo
    from cooldown.collectors.system import SystemStats
    from cooldown.collectors.thermal import ThermalStats

    app_cls = watch._build_app_class()
    app = app_cls(fast_interval=999, slow_interval=999)

    # Suppress the on_mount bootstrap workers so the test's explicit
    # _apply_ports / _apply_projects synthetic data isn't overwritten by
    # the real-machine port scan that the slow tick would otherwise run.
    # The test exercises the apply path itself, not the bootstrap timer.
    app._schedule_fast = lambda: None
    app._schedule_slow = lambda: None

    async with app.run_test() as pilot:
        # Feed synthetic data via the public apply path.
        mem = MemoryStats(
            total=64 * 1024**3, used=40 * 1024**3, available=20 * 1024**3,
            used_percent=62.5, wired=10 * 1024**3, compressed=5 * 1024**3,
            swap_total=10 * 1024**3, swap_used=1 * 1024**3,
            page_size=16384, pressure_level="warn",
        )
        sys_stats = SystemStats(
            cpu_percent=42.0, load_1=1.0, load_5=1.0, load_15=1.0,
            cpu_count_logical=10, cpu_count_physical=10,
            uptime=3600.0, total_processes=500,
        )
        therm = ThermalStats(
            thermal_warning="none", cpu_power_status="ok",
            low_power_mode=False, ac_power=True, battery_percent=100,
            display_sleep=10, disk_sleep=10, sleep_prevented=False,
        )
        proc = ProcInfo(
            pid=1234, ppid=1, kind="droid", name="droid", cmdline="droid run",
            rss=500 * 1024**2, cpu_percent=5.0, create_time=0.0, age=0.0,
            tty=None, user="me", idle_seconds=60.0,
        )
        await pilot.pause()
        app._apply_cpu(sys_stats)
        app._apply_mem(mem)
        app._apply_thermal(therm)
        ai_rows = watch.build_ai_rows([proc])
        app._apply_ai([proc], ai_rows)
        app._apply_projects([
            watch.ProjectRow(
                name="alpha", count=2, rss=1024**3,
                langs="node", launchers="tmux", orphan=False, pids=[10, 11],
            )
        ])
        app._apply_ports([
            watch.PortRow(
                port=4000, proto="tcp4", pid=9999,
                process="node", project="web", launcher="droid",
            )
        ])
        from cooldown.collectors import hot_procs as hot_mod
        app._apply_hot(
            [
                watch.HotAppRow(
                    app="python3.13", cores=0.98, pct_sys=9.8, nproc=1,
                    rss=600 * 1024**2, pids=[78303], origin_label="",
                    members=[
                        watch.HotMemberRow(
                            pid=78303, cores=0.98, pct_sys=9.8,
                            rss=600 * 1024**2, age=4 * 3600.0, cmd="python doctor.py",
                        )
                    ],
                )
            ],
            hot_mod.Coverage(
                total_pct_sys=9.8, shown_pct_sys=9.8, tail_pct_sys=0.0, tail_nproc=0
            ),
        )
        await pilot.pause()

        # All seven panels are mounted with the expected ids.
        for panel_id in ("cpu", "mem", "thermal", "ai", "projects", "hot", "ports"):
            assert app.query_one(f"#{panel_id}") is not None

        # Healthbar Static (which replaces the header subtitle) is populated
        # with markup-formatted status. Static.render() returns a Content
        # object whose __str__ gives us the rendered plain text.
        from textual.widgets import Static
        hb = app.query_one("#healthbar", Static)
        health_text = str(hb.render())
        assert "Health" in health_text
        assert "pressure" in health_text

        # DataTable rows landed.
        from textual.widgets import DataTable
        assert app.query_one("#ai", DataTable).row_count == 1
        assert app.query_one("#projects", DataTable).row_count == 1
        assert app.query_one("#ports", DataTable).row_count == 1
        # Hot-by-app renders one group row (collapsed, no members shown).
        assert app.query_one("#hot", DataTable).row_count == 1


def test_watch_app_binds_focus_hot_to_4():
    """The Hot Processes panel must be reachable via the `4` shortcut so
    the user can jump straight there when CPU is on fire."""
    app_cls = watch._build_app_class()
    keys = _binding_keys(app_cls.BINDINGS)
    assert "4" in keys, f"missing binding: '4' for hot procs (have {keys})"


def test_build_hot_app_rows_limits_members():
    """``build_hot_app_rows`` keeps the full per-app count but truncates the
    expandable member list so a 50-renderer Chrome doesn't blow the budget."""
    from cooldown.collectors import hot_procs as hot_mod
    procs = [
        hot_mod.HotProc(
            pid=i, name="Google Chrome", cmdline="Google Chrome --type=renderer",
            cpu_percent=1.0, rss=1, user="u", create_time=0.0, age=1.0,
            exe="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        )
        for i in range(20)
    ]
    apps, _ = hot_mod.aggregate_by_app(procs, ncpu=10, top_n=8)
    rows = watch.build_hot_app_rows(apps, ncpu=10, member_limit=5)
    assert len(rows) == 1  # all 20 collapse into one "Google Chrome"
    assert rows[0].nproc == 20  # full count preserved
    assert len(rows[0].members) == 5  # display members truncated


def test_targets_for_hot_group_and_member():
    """A group row signals every PID in the app; a member row signals just
    that one. This is what makes ``k`` safe on the aggregated view."""
    app_cls = watch._build_app_class()
    app = app_cls(fast_interval=999, slow_interval=999)
    grp = watch.HotAppRow(
        app="Google Chrome", cores=2.0, pct_sys=20.0, nproc=2,
        rss=1, pids=[111, 222], origin_label="", members=[],
    )
    member = watch.HotMemberRow(
        pid=222, cores=1.0, pct_sys=10.0, rss=1, age=1.0, cmd="renderer",
    )
    app._hot_visible = [("group", grp), ("member", member)]

    assert sorted(t.pid for t in app._targets_for("hot", 0)) == [111, 222]  # group → all
    one = app._targets_for("hot", 1)  # member → single pid
    assert [t.pid for t in one] == [222]
    assert one[0].cmdline == "renderer"
    # A plain (non-leftover) group keeps generic hot-app semantics.
    assert all(t.kind == "hot-app" for t in app._targets_for("hot", 0))
    # out-of-range / unknown row → nothing to kill
    assert app._targets_for("hot", 9) == []


def test_targets_for_hot_group_with_origin_uses_automation_browser_kind():
    """A hot-app group flagged as an automation-browser leftover must kill with
    kind='automation-browser' so reap expands the Chrome helper subtree; a plain
    'hot-app' kind would skip subtree expansion and leave idle helpers alive."""
    app_cls = watch._build_app_class()
    app = app_cls(fast_interval=999, slow_interval=999)
    grp = watch.HotAppRow(
        app="Google Chrome", cores=2.0, pct_sys=20.0, nproc=2,
        rss=1, pids=[111, 222], origin_label="⚠ agent-browser leftover", members=[],
    )
    app._hot_visible = [("group", grp)]

    targets = app._targets_for("hot", 0)
    assert {t.pid for t in targets} == {111, 222}
    assert all(t.kind == "automation-browser" for t in targets)

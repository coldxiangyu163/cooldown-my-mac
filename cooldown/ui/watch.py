"""`cool watch` — Textual full-screen live dashboard.

Layout
------
A 3-row × 2-col grid of panels::

    +---------------+---------------+
    |      CPU      |     Memory    |     (fast tick)
    +---------------+---------------+
    |    Thermal    |    AI CLI     |     (fast tick)
    +---------------+---------------+
    | Top Projects  |   Top Ports   |     (slow tick)
    +---------------+---------------+

Timers
------
Two independent refresh timers:

* ``fast_interval`` (default 3s): CPU / Memory / Thermal / AI CLI
* ``slow_interval`` (default 15s): Top Projects / Top Ports

Each tick is dispatched to a Textual thread worker (one per group) so the
UI event loop never blocks on ``psutil`` sampling or ``lsof`` shell-outs.

Interactivity
-------------
The three tabular panels (AI CLI / Top Projects / Top Ports) are
``DataTable`` widgets and accept keyboard focus. Navigate with Tab and
arrow keys; press ``k`` to SIGTERM the process(es) in the selected row
(``K`` / ``ctrl+k`` escalates to SIGKILL). All kill actions go through
the shared :func:`cooldown.actions.reap.terminate` path, which enforces
self-protection and writes to the oplog.

Error isolation
---------------
Each collector runs inside its own try/except. A failure in any one of
them renders ``[red]collector error[/]`` inline on that panel only, so a
single flaky probe (macOS ``sysctl(KERN_PROCARGS2)`` EPERM, a transient
ZombieProcess, etc.) never takes down the whole TUI.
"""
from __future__ import annotations

import contextlib
import json
import time
from dataclasses import dataclass
from typing import Any

from rich.console import Console

from ..collectors import battery as batt_mod
from ..collectors import dev as dev_mod
from ..collectors import hostinfo as host_mod
from ..collectors import memory as mem_mod
from ..collectors import ports as ports_mod
from ..collectors import procs as procs_mod
from ..collectors import system as sys_mod
from ..collectors import thermal as therm_mod
from ..collectors.procs import ProcInfo
from ..safety.oplog import LOG_PATH
from ..util import human_bytes, human_duration
from .dashboard import (
    _battery_content,
    _cpu_content,
    _health_score,
    _mem_content,
    _thermal_content,
)

# ---------------------------------------------------------------------------
# Data-table row helpers (pure functions — easy to unit-test)
# ---------------------------------------------------------------------------

@dataclass
class AiRow:
    kind: str
    count: int
    rss: int
    cpu: float
    idle: float
    pids: list[int]


@dataclass
class ProjectRow:
    name: str
    count: int
    rss: int
    langs: str
    launchers: str
    orphan: bool
    pids: list[int]


@dataclass
class PortRow:
    port: int
    proto: str
    pid: int
    process: str
    project: str
    launcher: str


def build_ai_rows(procs: list[ProcInfo], limit: int = 20) -> list[AiRow]:
    groups = procs_mod.group_by_kind(procs)
    out: list[AiRow] = []
    for kind, items in groups.items():
        out.append(
            AiRow(
                kind=kind,
                count=len(items),
                rss=sum(p.rss for p in items),
                cpu=sum(p.cpu_percent for p in items),
                idle=max((p.idle_seconds or 0.0) for p in items),
                pids=[p.pid for p in items],
            )
        )
    return out[:limit]


def build_project_rows(devs: list[dev_mod.DevProc], limit: int = 12) -> list[ProjectRow]:
    groups = dev_mod.group_by(devs, "project")
    if not groups:
        return []
    ranked = sorted(groups.items(), key=lambda kv: -sum(d.rss for d in kv[1]))[:limit]
    return [
        ProjectRow(
            name=name,
            count=len(items),
            rss=sum(d.rss for d in items),
            langs=",".join(sorted({d.lang for d in items})),
            launchers=",".join(sorted({d.launcher.kind for d in items})),
            orphan=any(d.is_orphan for d in items),
            pids=[d.pid for d in items],
        )
        for name, items in ranked
    ]


def build_port_rows(
    entries: list[ports_mod.PortEntry],
    launchers: dict[int, str],
    projects: dict[int, str],
    limit: int = 20,
) -> list[PortRow]:
    # Dedup per (port, pid) so tcp4/tcp6 twin rows don't both appear.
    seen: set[tuple[int, int]] = set()
    out: list[PortRow] = []
    for e in sorted(entries, key=lambda x: (x.port, x.pid)):
        key = (e.port, e.pid)
        if key in seen:
            continue
        seen.add(key)
        out.append(
            PortRow(
                port=e.port,
                proto=e.proto,
                pid=e.pid,
                process=e.process,
                project=projects.get(e.pid, "-") or "-",
                launcher=launchers.get(e.pid, "-") or "-",
            )
        )
        if len(out) >= limit:
            break
    return out


# ---------------------------------------------------------------------------
# Oplog "last action" tail (cheap — reads last non-empty line)
# ---------------------------------------------------------------------------

def _last_oplog_entry(max_bytes: int = 4096) -> tuple[str, float] | None:
    """Return (action_str, epoch_seconds) for the most recent oplog line.

    Reads only the trailing ``max_bytes`` so the call is O(1) regardless of
    log size. Returns ``None`` on any failure.
    """
    try:
        if not LOG_PATH.exists():
            return None
        size = LOG_PATH.stat().st_size
        with LOG_PATH.open("rb") as f:
            f.seek(max(0, size - max_bytes))
            chunk = f.read().decode("utf-8", errors="replace")
        last = None
        for line in chunk.splitlines():
            line = line.strip()
            if line:
                last = line
        if not last:
            return None
        obj = json.loads(last)
        ts_s = obj.get("ts") or ""
        action = obj.get("action") or "?"
        # Parse isoformat (with seconds precision).
        if ts_s:
            import datetime as _dt  # noqa: PLC0415
            try:
                ts = _dt.datetime.fromisoformat(ts_s).timestamp()
            except ValueError:
                ts = time.time()
        else:
            ts = time.time()
        return action, ts
    except Exception:  # noqa: BLE001
        return None


# ---------------------------------------------------------------------------
# Dense single-line header (mo status-inspired) — crams machine identity,
# health score, key thermal metrics, and live tick cadence into one row.
# ---------------------------------------------------------------------------

def render_subtitle(
    *,
    mem: mem_mod.MemoryStats | None,
    sys_stats: sys_mod.SystemStats | None,
    therm: therm_mod.ThermalStats | None,
    procs: list[ProcInfo] | None,
    last_op: tuple[str, float] | None,
    fast_interval: int,
    slow_interval: int,
    paused: bool,
    dry_run: bool,
    host: host_mod.HostInfo | None = None,
    battery: batt_mod.BatteryStats | None = None,
) -> str:
    bits: list[str] = []

    # 1. Health dot (lights up the eye first).
    if mem and sys_stats and therm:
        score, color = _health_score(mem, sys_stats, therm)
        bits.append(f"Health [{color}]●{score}[/]")

    # 2. Machine identity: model · chip · topology · RAM/Disk · macOS.
    if host is not None:
        chip = host.chip.replace("Apple ", "")
        gpu = f", {host.gpu_cores}GPU" if host.gpu_cores else ""
        ram_gb = host.ram_bytes / 1024 / 1024 / 1024
        disk_tb = host.disk_total_bytes / 1024 ** 4
        bits.append(
            f"[cyan]{host.model}[/] · [yellow]{chip}{gpu}[/] [dim]{host.topology}[/] "
            f"· {ram_gb:.0f}G/{disk_tb:.1f}T · macOS {host.macos_version}"
        )

    # 3. Uptime.
    if sys_stats:
        bits.append(f"up [dim]{human_duration(sys_stats.uptime)}[/]")

    # 4. Battery temp (not AC state — temp is the thermal-management signal).
    if battery and battery.temp_c is not None:
        t = battery.temp_c
        tc = "bold red" if t >= 40 else "yellow" if t >= 35 else "green"
        tail = ""
        if battery.percent is not None:
            tail = f" [dim]{battery.percent:.0f}%[/]"
            if battery.charging:
                tail += " [dim green]⚡[/]"
        bits.append(f"batt [{tc}]{t:.1f}°C[/]{tail}")

    # 5. Memory pressure (explicit label so it's scannable).
    if mem:
        lvl = mem.pressure_level or "?"
        lvl_color = {
            "normal": "green", "warn": "yellow", "critical": "bold red"
        }.get(lvl, "dim")
        bits.append(f"pressure [{lvl_color}]{lvl}[/]")

    # 6. AI CLI fleet size.
    if procs is not None:
        bits.append(f"CLIs [cyan]{len(procs)}[/]")

    # 7. Last operation echo (dims older entries).
    if last_op:
        action, ts = last_op
        ago = max(0, time.time() - ts)
        bits.append(f"last [dim]{action}[/] [dim]{human_duration(ago)} ago[/]")

    # 8. Tick cadence + state flags.
    bits.append(f"[dim]⟳ {fast_interval}s/{slow_interval}s[/]")
    if paused:
        bits.append("[yellow]paused[/]")
    if dry_run:
        bits.append("[magenta]dry-run[/]")
    return "  ·  ".join(bits)


# ---------------------------------------------------------------------------
# Textual App (built lazily so `import cooldown.ui.watch` is cheap)
# ---------------------------------------------------------------------------

def _build_app_class():
    from textual.app import App
    from textual.containers import Grid
    from textual.widgets import DataTable, Footer, Header, Static

    class CooldownWatchApp(App):
        """Full-screen live dashboard for ``cool watch``."""

        TITLE = "cooldown · watch"

        CSS = """
        Screen { layout: vertical; }
        Header { dock: top; }
        Footer { dock: bottom; }

        #healthbar {
            dock: top;
            height: 1;
            padding: 0 1;
            background: $panel;
            color: $text;
        }

        #body {
            layout: grid;
            grid-size: 2 4;
            grid-gutter: 0 1;
            padding: 0 1;
            height: 1fr;
        }

        .panel {
            border: round $primary;
            padding: 0 1;
            height: 1fr;
            min-height: 6;
        }
        DataTable.panel {
            border: round $accent;
        }
        DataTable.panel > .datatable--cursor {
            background: $accent 40%;
        }
        DataTable:focus.panel {
            border: thick $accent;
        }

        /* Ports gets the full bottom row — wide tables read much better
           than narrow ones when attribution columns pile up. */
        #ports {
            column-span: 2;
        }
        """

        BINDINGS = [
            ("q", "quit", "Quit"),
            ("r", "refresh_fast", "Refresh"),
            ("R", "refresh_slow", "Refresh slow"),
            ("p", "toggle_pause", "Pause"),
            ("d", "toggle_dry_run", "Dry-run"),
            ("k", "kill_selected", "Kill"),
            ("K", "kill_selected_force", "Force kill"),
            ("1", "focus_ai", "AI table"),
            ("2", "focus_projects", "Projects"),
            ("3", "focus_ports", "Ports"),
            ("plus,equals_sign", "faster_fast", "Faster"),
            ("minus,underscore", "slower_fast", "Slower"),
            ("bracket_left", "faster_slow", "Slow+"),
            ("bracket_right", "slower_slow", "Slow-"),
        ]

        def __init__(self, *, fast_interval: int = 3, slow_interval: int = 15) -> None:
            super().__init__()
            self.fast_interval = max(1, int(fast_interval))
            self.slow_interval = max(3, int(slow_interval))
            self.paused = False
            self.dry_run = False
            self._fast_timer: Any = None
            self._slow_timer: Any = None
            # Last-known data (used for the subtitle + kill action).
            self._mem: mem_mod.MemoryStats | None = None
            self._sys: sys_mod.SystemStats | None = None
            self._therm: therm_mod.ThermalStats | None = None
            self._batt: batt_mod.BatteryStats | None = None
            self._host: host_mod.HostInfo | None = None
            self._procs: list[ProcInfo] | None = None
            self._ai_rows: list[AiRow] = []
            self._project_rows: list[ProjectRow] = []
            self._port_rows: list[PortRow] = []
            # Per-panel "last updated" epoch.
            self._updated: dict[str, float] = {}

        # ---------------------------------------------------------- compose
        def compose(self):
            yield Header(show_clock=True)
            yield Static("[dim]booting…[/]", id="healthbar", markup=True)
            cpu = Static("[dim]sampling…[/]", id="cpu", classes="panel")
            cpu.border_title = "CPU"
            mem = Static("[dim]sampling…[/]", id="mem", classes="panel")
            mem.border_title = "Memory"
            therm = Static("[dim]sampling…[/]", id="thermal", classes="panel")
            therm.border_title = "Thermal"
            batt = Static("[dim]sampling…[/]", id="battery", classes="panel")
            batt.border_title = "Battery"
            ai = DataTable(id="ai", classes="panel", cursor_type="row", zebra_stripes=True)
            ai.border_title = "AI CLI Inventory  [dim](focus + k = reap)[/]"
            proj = DataTable(id="projects", classes="panel", cursor_type="row", zebra_stripes=True)
            proj.border_title = "Top Projects by RSS"
            ports = DataTable(id="ports", classes="panel", cursor_type="row", zebra_stripes=True)
            ports.border_title = "Listening Ports"
            yield Grid(cpu, mem, therm, batt, ai, proj, ports, id="body")
            yield Footer()

        # ---------------------------------------------------------- mount
        def on_mount(self) -> None:
            # Configure the DataTables once.
            ai: DataTable = self.query_one("#ai", DataTable)
            ai.add_columns("kind", "count", "rss", "cpu%", "idle(max)")
            proj: DataTable = self.query_one("#projects", DataTable)
            proj.add_columns("project", "#", "rss", "langs", "launchers")
            ports: DataTable = self.query_one("#ports", DataTable)
            ports.add_columns("port", "proto", "pid", "process", "project", "launcher")

            # Host identity is immutable — read it once at startup so the
            # header can render it without a per-tick subprocess spawn.
            try:
                self._host = host_mod.collect()
            except Exception:  # noqa: BLE001
                self._host = None

            self._reset_fast_timer()
            self._reset_slow_timer()
            # Kick off both now so panels don't sit empty.
            self._schedule_fast()
            self._schedule_slow()
            self._refresh_subtitle()

        # ---------------------------------------------------------- timers
        def _reset_fast_timer(self) -> None:
            if self._fast_timer is not None:
                self._fast_timer.stop()
            self._fast_timer = self.set_interval(self.fast_interval, self._schedule_fast)

        def _reset_slow_timer(self) -> None:
            if self._slow_timer is not None:
                self._slow_timer.stop()
            self._slow_timer = self.set_interval(self.slow_interval, self._schedule_slow)

        def _schedule_fast(self) -> None:
            if self.paused:
                return
            self.run_worker(
                self._gather_fast, thread=True, exclusive=True, group="cooldown-fast"
            )

        def _schedule_slow(self) -> None:
            if self.paused:
                return
            self.run_worker(
                self._gather_slow, thread=True, exclusive=True, group="cooldown-slow"
            )

        # ---------------------------------------------------------- collectors
        def _gather_fast(self) -> None:
            try:
                sys_stats = sys_mod.collect(cpu_sample=0.2)
                self.call_from_thread(self._apply_cpu, sys_stats)
            except Exception as exc:  # noqa: BLE001
                self.call_from_thread(self._set_error, "cpu", exc)
            try:
                mem = mem_mod.collect()
                self.call_from_thread(self._apply_mem, mem)
            except Exception as exc:  # noqa: BLE001
                self.call_from_thread(self._set_error, "mem", exc)
            try:
                therm = therm_mod.collect()
                self.call_from_thread(self._apply_thermal, therm)
            except Exception as exc:  # noqa: BLE001
                self.call_from_thread(self._set_error, "thermal", exc)
            try:
                batt = batt_mod.collect()
                self.call_from_thread(self._apply_battery, batt)
            except Exception as exc:  # noqa: BLE001
                self.call_from_thread(self._set_error, "battery", exc)
            try:
                procs = procs_mod.collect(sample_interval=0.1)
                procs_mod.enrich_idle(procs)
                procs.sort(key=lambda p: -p.rss)
                ai_rows = build_ai_rows(procs)
                self.call_from_thread(self._apply_ai, procs, ai_rows)
            except Exception as exc:  # noqa: BLE001
                self.call_from_thread(self._set_table_error, "ai", exc)

        def _gather_slow(self) -> None:
            try:
                devs = dev_mod.collect(sample_interval=0.1)
                rows = build_project_rows(devs)
                self.call_from_thread(self._apply_projects, rows)
            except Exception as exc:  # noqa: BLE001
                self.call_from_thread(self._set_table_error, "projects", exc)
            try:
                entries = ports_mod.collect()
                # Best-effort attribution — lazy to keep slow-tick below 1s.
                launchers: dict[int, str] = {}
                projects: dict[int, str] = {}
                try:
                    from ..collectors import ancestry as ancestry_mod  # noqa: PLC0415
                    from ..collectors import project as project_mod  # noqa: PLC0415
                    for pid in {e.pid for e in entries}:
                        try:
                            lnc = ancestry_mod.find_launcher(pid)
                            launchers[pid] = getattr(lnc, "label", None) or getattr(
                                lnc, "kind", "-"
                            )
                        except Exception:  # noqa: BLE001
                            launchers[pid] = "-"
                        try:
                            proj = project_mod.lookup(pid)
                            projects[pid] = proj.name if proj else "-"
                        except Exception:  # noqa: BLE001
                            projects[pid] = "-"
                except Exception:  # noqa: BLE001
                    pass
                rows = build_port_rows(entries, launchers, projects)
                self.call_from_thread(self._apply_ports, rows)
            except Exception as exc:  # noqa: BLE001
                self.call_from_thread(self._set_table_error, "ports", exc)

        # ---------------------------------------------------------- apply (UI thread)
        def _apply_cpu(self, sys_stats: sys_mod.SystemStats) -> None:
            self._sys = sys_stats
            self._updated["cpu"] = time.time()
            self.query_one("#cpu", Static).update(_cpu_content(sys_stats))
            self._refresh_subtitle()

        def _apply_mem(self, mem: mem_mod.MemoryStats) -> None:
            self._mem = mem
            self._updated["mem"] = time.time()
            self.query_one("#mem", Static).update(_mem_content(mem))
            self._refresh_subtitle()

        def _apply_thermal(self, therm: therm_mod.ThermalStats) -> None:
            self._therm = therm
            self._updated["thermal"] = time.time()
            self.query_one("#thermal", Static).update(_thermal_content(therm))
            self._refresh_subtitle()

        def _apply_battery(self, batt: batt_mod.BatteryStats | None) -> None:
            self._batt = batt
            self._updated["battery"] = time.time()
            self.query_one("#battery", Static).update(_battery_content(batt))
            self._refresh_subtitle()

        def _apply_ai(self, procs: list[ProcInfo], rows: list[AiRow]) -> None:
            self._procs = procs
            self._ai_rows = rows
            self._updated["ai"] = time.time()
            t: DataTable = self.query_one("#ai", DataTable)
            t.clear()
            for row in rows:
                style = "[yellow]" if row.kind in procs_mod.AI_KINDS else "[cyan]"
                t.add_row(
                    f"{style}{row.kind}[/]",
                    str(row.count),
                    human_bytes(row.rss),
                    f"{row.cpu:.1f}",
                    human_duration(row.idle),
                )
            # Show aggregate stats in the title.
            total_rss = sum(r.rss for r in rows)
            total = sum(r.count for r in rows)
            t.border_title = (
                f"AI CLI Inventory · {total} procs · {human_bytes(total_rss)}  "
                "[dim](k = reap kind)[/]"
            )
            self._refresh_subtitle()

        def _apply_projects(self, rows: list[ProjectRow]) -> None:
            self._project_rows = rows
            self._updated["projects"] = time.time()
            t: DataTable = self.query_one("#projects", DataTable)
            t.clear()
            for row in rows:
                name_cell = f"[red]{row.name}[/]" if row.orphan else row.name
                t.add_row(
                    name_cell,
                    str(row.count),
                    human_bytes(row.rss),
                    row.langs,
                    row.launchers,
                )
            total_rss = sum(r.rss for r in rows)
            t.border_title = (
                f"Top Projects by RSS · {len(rows)} shown · "
                f"{human_bytes(total_rss)}"
            )

        def _apply_ports(self, rows: list[PortRow]) -> None:
            self._port_rows = rows
            self._updated["ports"] = time.time()
            t: DataTable = self.query_one("#ports", DataTable)
            t.clear()
            for row in rows:
                t.add_row(
                    str(row.port),
                    row.proto,
                    str(row.pid),
                    row.process,
                    row.project,
                    row.launcher,
                )
            t.border_title = f"Listening Ports · {len(rows)} shown  [dim](k = kill pid)[/]"

        def _set_error(self, panel_id: str, exc: BaseException) -> None:
            with contextlib.suppress(Exception):
                self.query_one(f"#{panel_id}", Static).update(
                    f"[red]collector error[/]\n[dim]{type(exc).__name__}: {exc}[/]"
                )

        def _set_table_error(self, panel_id: str, exc: BaseException) -> None:
            with contextlib.suppress(Exception):
                t = self.query_one(f"#{panel_id}", DataTable)
                t.clear()
                t.border_title = (
                    f"{t.border_title}  [red]· error: {type(exc).__name__}[/]"
                )

        # ---------------------------------------------------------- healthbar
        def _refresh_subtitle(self) -> None:
            markup = render_subtitle(
                mem=self._mem,
                sys_stats=self._sys,
                therm=self._therm,
                procs=self._procs,
                last_op=_last_oplog_entry(),
                fast_interval=self.fast_interval,
                slow_interval=self.slow_interval,
                paused=self.paused,
                dry_run=self.dry_run,
                host=self._host,
                battery=self._batt,
            )
            with contextlib.suppress(Exception):
                self.query_one("#healthbar", Static).update(markup)

        # ---------------------------------------------------------- actions
        def action_refresh_fast(self) -> None:
            self._schedule_fast()
            self.notify("fast refresh queued", timeout=1.0)

        def action_refresh_slow(self) -> None:
            self._schedule_slow()
            self.notify("slow refresh queued", timeout=1.0)

        def action_toggle_pause(self) -> None:
            self.paused = not self.paused
            self.notify("paused" if self.paused else "resumed", timeout=1.0)
            self._refresh_subtitle()

        def action_toggle_dry_run(self) -> None:
            self.dry_run = not self.dry_run
            self.notify(
                "kill actions → DRY-RUN" if self.dry_run else "kill actions → LIVE",
                severity="information" if self.dry_run else "warning",
                timeout=1.5,
            )
            self._refresh_subtitle()

        def action_focus_ai(self) -> None:
            self.query_one("#ai", DataTable).focus()

        def action_focus_projects(self) -> None:
            self.query_one("#projects", DataTable).focus()

        def action_focus_ports(self) -> None:
            self.query_one("#ports", DataTable).focus()

        def action_faster_fast(self) -> None:
            self.fast_interval = max(1, self.fast_interval - 1)
            self._reset_fast_timer()
            self._refresh_subtitle()
            self.notify(f"fast interval: {self.fast_interval}s", timeout=1.0)

        def action_slower_fast(self) -> None:
            self.fast_interval = min(60, self.fast_interval + 1)
            self._reset_fast_timer()
            self._refresh_subtitle()
            self.notify(f"fast interval: {self.fast_interval}s", timeout=1.0)

        def action_faster_slow(self) -> None:
            self.slow_interval = max(3, self.slow_interval - 5)
            self._reset_slow_timer()
            self._refresh_subtitle()
            self.notify(f"slow interval: {self.slow_interval}s", timeout=1.0)

        def action_slower_slow(self) -> None:
            self.slow_interval = min(300, self.slow_interval + 5)
            self._reset_slow_timer()
            self._refresh_subtitle()
            self.notify(f"slow interval: {self.slow_interval}s", timeout=1.0)

        # ---------------------------------------------------------- kill
        def action_kill_selected(self) -> None:
            self._kill_selected(force=False)

        def action_kill_selected_force(self) -> None:
            self._kill_selected(force=True)

        def _kill_selected(self, *, force: bool) -> None:
            focused = self.focused
            if not isinstance(focused, DataTable):
                self.notify(
                    "focus a table first (Tab, or press 1/2/3)",
                    severity="warning",
                    timeout=2.0,
                )
                return
            table_id = focused.id or ""
            try:
                row_idx = focused.cursor_row
            except Exception:  # noqa: BLE001
                row_idx = None
            if row_idx is None or row_idx < 0:
                self.notify("no row selected", severity="warning", timeout=1.5)
                return

            targets = self._targets_for(table_id, row_idx)
            if not targets:
                self.notify("no killable pids on this row", severity="warning", timeout=1.5)
                return

            sig = "SIGKILL" if force else "SIGTERM"
            mode = "DRY-RUN" if self.dry_run else sig
            self.notify(
                f"{mode} {len(targets)} pid(s)…",
                severity="warning" if not self.dry_run else "information",
                timeout=2.0,
            )
            # Run the kill in a background thread so the UI doesn't block
            # on `psutil.wait(timeout=3)`.
            self.run_worker(
                lambda: self._do_kill(targets, force=force),
                thread=True,
                exclusive=False,
                group="cooldown-kill",
            )

        def _targets_for(self, table_id: str, row_idx: int) -> list[ProcInfo]:
            """Map (table, row) → list[ProcInfo] suitable for reap.terminate."""
            if table_id == "ai":
                if 0 <= row_idx < len(self._ai_rows):
                    row = self._ai_rows[row_idx]
                    if not self._procs:
                        return []
                    pid_set = set(row.pids)
                    return [p for p in self._procs if p.pid in pid_set]
            elif table_id == "projects" and 0 <= row_idx < len(self._project_rows):
                row = self._project_rows[row_idx]
                # Rebuild lightweight ProcInfo records for the pids.
                return [_synth_procinfo(pid, "dev", row.name) for pid in row.pids]
            elif table_id == "ports" and 0 <= row_idx < len(self._port_rows):
                row = self._port_rows[row_idx]
                return [_synth_procinfo(row.pid, "port", f":{row.port}")]
            return []

        def _do_kill(self, targets: list[ProcInfo], *, force: bool) -> None:
            from ..actions.reap import terminate  # noqa: PLC0415
            try:
                outcomes = terminate(targets, dry_run=self.dry_run, force=force)
            except Exception as exc:  # noqa: BLE001
                self.call_from_thread(
                    self.notify,
                    f"kill failed: {type(exc).__name__}: {exc}",
                    severity="error",
                    timeout=4.0,
                )
                return
            ok = sum(1 for o in outcomes if o.ok)
            failed = len(outcomes) - ok
            msg = f"{ok} ok · {failed} failed"
            self.call_from_thread(
                self.notify,
                msg,
                severity="information" if failed == 0 else "warning",
                timeout=3.0,
            )
            # Immediately refresh fast + (if we killed from projects/ports)
            # slow so the user sees their row disappear.
            self.call_from_thread(self._schedule_fast)
            self.call_from_thread(self._schedule_slow)

    return CooldownWatchApp


def _synth_procinfo(pid: int, kind: str, cmdline: str) -> ProcInfo:
    """Build a minimal ProcInfo for the kill path when we only know pid."""
    return ProcInfo(
        pid=pid,
        ppid=0,
        kind=kind,
        name=str(pid),
        cmdline=cmdline,
        rss=0,
        cpu_percent=0.0,
        create_time=0.0,
        age=0.0,
        tty=None,
        user="",
    )


def run(
    console: Console, *, interval: int = 3, slow_interval: int = 15
) -> int:
    """Launch the ``cool watch`` full-screen dashboard.

    ``interval`` is the fast-tick interval (CPU/Mem/Thermal/AI CLI).
    ``slow_interval`` is the slow-tick interval (Top Projects/Top Ports).
    """
    try:
        app_cls = _build_app_class()
    except ImportError:
        console.print(
            "[red]textual is not installed[/] — required for `cool watch`.\n"
            "[dim]install it with one of:[/]\n"
            "  [cyan]pipx inject cooldown-my-mac textual[/]\n"
            "  [cyan]pip install textual[/]"
        )
        return 1
    app = app_cls(fast_interval=interval, slow_interval=slow_interval)
    app.run()
    return 0

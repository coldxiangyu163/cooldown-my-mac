"""`cool watch` — Textual full-screen live dashboard.

Layout
------
A 4-row × 2-col grid plus a dense single-line healthbar header. The
bottom row (Listening Ports) spans both columns::

    ┌─ healthbar: Health │ alerts │ context │ identity │ meta ─────┐
    +---------------+---------------+
    |      CPU      |     Memory    |     fast  · fast
    +---------------+---------------+
    |    Thermal    |    Battery    |     fast  · fast
    +---------------+---------------+
    |    AI CLI     | Top Projects  |     fast  · slow
    +---------------+---------------+
    |       Listening Ports         |     slow
    +-------------------------------+

Per-cell tick mapping (a panel refreshes only when its tick fires):

Timers
------
Two independent refresh timers:

* ``fast_interval`` (default 3s): CPU / Memory / Thermal / Battery / AI CLI
* ``slow_interval`` (default 15s): Top Projects / Listening Ports

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
import logging
import time
from collections import deque
from dataclasses import dataclass
from typing import Any

from rich.console import Console
from rich.text import Text

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
    battery_title_summary as _battery_title_summary,
    chip_tokens as _chip_tokens,
    cpu_title_summary as _cpu_title_summary,
    idle_color as _idle_color,
    mem_title_summary as _mem_title_summary,
    thermal_title_summary as _thermal_title_summary,
)
from .dashboard import (
    decorate_project_name as _decorate_project_name,
)
from .dashboard import (
    kind_color as _kind_color,
)

log = logging.getLogger("cooldown.watch")

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
    """Compose the slim, designer-tuned header bar above the panel grid.

    Layout reads left-to-right as a single calm strip:

        ┃ ● 70 ┃   ⚠ pressure  ⚠ thermal  ◐ sleep  🌡 41°  ·  CLIs 66  ·  last … ┃   MacBook Pro · M1 Max · 64GB   ┃ ⟳ 3/15s  · ● dry-run ┃

    Design rules — keep the bar quiet by default, escalate visually
    only when something is wrong:

    * **Health badge** is a high-contrast pill with the score inside.
      It anchors the eye and is the only place colour-on-colour appears.
    * **Alerts** become icon-led chips (⚠ / ◐ / ◉). Icon + colour carries
      severity so the prose ("critical" / "warn") can stay short.
    * **Context** (CLI count, last op) sits at normal weight — useful but
      not screaming.
    * **Identity** is one dim run (no more dot-soup): users glance at it
      once and ignore it after.
    * **Meta** (cadence + mode flags) lives at the right edge so the
      reading rhythm always ends in the same place.

    Wide three-space gaps replace the old ``│`` dividers because, at
    panel width, the eye already chunks by spacing — the explicit pipe
    was adding noise without adding signal.
    """
    chunks: list[str] = []

    # Chunk 1 — Health pill. Inverted color block puts the only piece of
    # heavy weight on screen on the score itself, which is what the user
    # actually scans for.
    if mem and sys_stats and therm:
        score, color = _health_score(mem, sys_stats, therm, battery)
        # Pill + dim "Health" label: pill carries the value, label tells
        # a first-time reader what the value means.
        chunks.append(
            f"[bold black on {color}]  ● {score}  [/] [dim]Health[/]"
        )

    # Chunk 2 — Live signals. Icons do the heavy lifting so we can drop
    # the level-name suffixes ("critical" / "warn") that previously made
    # every alert feel like an emergency.
    signals: list[str] = []
    if mem:
        lvl = mem.pressure_level or "?"
        # Icon + colour carries severity; level word is appended dim so
        # the screenshot stays legible without the word fighting the
        # icon for visual weight.
        if lvl == "critical":
            signals.append("[bold red]⚠ pressure[/] [dim]critical[/]")
        elif lvl == "warn":
            signals.append("[yellow]⚠ pressure[/] [dim]warn[/]")
        # normal/unknown intentionally silent — the Health pill already
        # encodes that state, so repeating it here only adds noise.
    if therm and therm.thermal_warning and therm.thermal_warning != "none":
        signals.append(
            f"[bold red]⚠ thermal[/] [dim]{therm.thermal_warning}[/]"
        )
    if therm and therm.sleep_prevented:
        signals.append("[yellow]◐ sleep blocked[/]")
    if battery and battery.temp_c is not None:
        t = battery.temp_c
        # One decimal preserved — battery cell temp moves slowly, so a
        # 0.5°C step is a meaningful trend signal worth showing.
        if t >= 40:
            signals.append(f"[bold red]🌡 batt {t:.1f}°C[/]")
        elif t >= 35:
            signals.append(f"[yellow]🌡 batt {t:.1f}°C[/]")
        # below 35°C is the normal state — omit so the bar stays empty
        # when there is nothing to react to.
    if procs is not None:
        signals.append(f"[dim]CLIs[/] [cyan]{len(procs)}[/]")
    # last_op intentionally NOT surfaced here — it was debug/meta
    # noise that pushed the bar density up. The oplog is still
    # written and `cool log` can show it for forensics.
    if signals:
        chunks.append("  ".join(signals))

    # Chunk 3 — Identity. Trimmed to the essentials the user actually
    # references during a session (model + chip + topology + RAM +
    # macOS). Dropped disk total + uptime because they're rarely
    # relevant during live monitoring and they pushed the bar past
    # typical terminal widths, hiding the clock + cadence at the
    # right edge.
    if host is not None:
        chip = host.chip.replace("Apple ", "")
        gpu = f", {host.gpu_cores}GPU" if host.gpu_cores else ""
        ident_bits = [
            f"{host.model} · {chip}{gpu} {host.topology}",
            f"{human_bytes(host.ram_bytes)} RAM",
            f"macOS {host.macos_version}",
        ]
        chunks.append(f"[dim]{' · '.join(ident_bits)}[/]")

    # Chunk 4 — Meta strip. Cadence (⟳ Xs/Ys) was dropped — it's a
    # static configuration value, not live data, and was crowding the
    # bar. Mode flags (paused / dry-run) keep their glyph so the user
    # can see at-a-glance they're in a non-default state. Clock anchors
    # the right edge — same place every C-end OS status bar puts it.
    meta_bits: list[str] = []
    if paused:
        meta_bits.append("[yellow]◼ paused[/]")
    if dry_run:
        meta_bits.append("[magenta]● dry-run[/]")
    meta_bits.append(f"[dim]{time.strftime('%H:%M')}[/]")
    chunks.append("  ".join(meta_bits))

    return "   ".join(c for c in chunks if c)


# ---------------------------------------------------------------------------
# Bulk port attribution
# ---------------------------------------------------------------------------
# Walking the ancestor chain + reading cwd for every listening pid in the
# slow tick used to be the worst single hotspot in this dashboard: N
# independent psutil.Process(...) calls + N classify_ancestor walks + N
# project.find_root scans of the filesystem.  Two layers of caching here
# collapse that to roughly O(unique-ancestor-pids + unique-cwds):
#
#   * `_classify_cache` memoises classify_ancestor() by ancestor pid so the
#     iTerm / tmux / shell ancestors shared by every child are only walked
#     once per slow tick.
#   * `_root_cache` memoises project.find_root() by cwd string so 10
#     subprocesses sharing the same project root only stat the marker set
#     once.

def _attribute_ports(pids: set[int]) -> tuple[dict[int, str], dict[int, str]]:
    """Return (launchers, projects) keyed by pid for the supplied set.

    Errors per pid degrade silently to ``"-"`` so a single PROC_ERRORS
    blip never wipes out the table.
    """
    try:
        from ..collectors import ancestry as ancestry_mod  # noqa: PLC0415
        from ..collectors import project as project_mod  # noqa: PLC0415
    except Exception:  # noqa: BLE001
        log.exception("watch: ancestry/project import failed")
        return {pid: "-" for pid in pids}, {pid: "-" for pid in pids}

    launchers: dict[int, str] = {}
    projects: dict[int, str] = {}

    _classify_cache: dict[int, Any] = {}

    def _classify(anc) -> Any:
        cached = _classify_cache.get(anc.pid)
        if cached is not None:
            return cached
        try:
            guess = ancestry_mod.classify_ancestor(anc)
        except Exception:  # noqa: BLE001
            guess = None
        _classify_cache[anc.pid] = guess
        return guess

    _root_cache: dict[str, Any] = {}

    def _project_for(pid: int) -> str:
        try:
            cwd = project_mod.get_cwd(pid)
        except Exception:  # noqa: BLE001
            return "-"
        if not cwd:
            return "-"
        if cwd in _root_cache:
            proj = _root_cache[cwd]
        else:
            try:
                proj = project_mod.find_root(cwd)
            except Exception:  # noqa: BLE001
                proj = None
            _root_cache[cwd] = proj
        return proj.name if proj else "-"

    for pid in pids:
        try:
            ancestors = ancestry_mod.walk(pid)
            launcher_label = "-"
            for anc in ancestors:
                guess = _classify(anc)
                if guess is None or guess.kind == "shell":
                    continue
                launcher_label = guess.label or guess.kind or "-"
                break
            launchers[pid] = launcher_label
        except Exception:  # noqa: BLE001
            launchers[pid] = "-"
        projects[pid] = _project_for(pid)

    return launchers, projects


# ---------------------------------------------------------------------------
# Textual App (built lazily so `import cooldown.ui.watch` is cheap)
# ---------------------------------------------------------------------------

def _build_app_class():
    from textual.app import App
    from textual.binding import Binding
    from textual.containers import Grid
    from textual.widgets import DataTable, Footer, Static

    class CooldownWatchApp(App):
        """Full-screen live dashboard for ``cool watch``."""

        TITLE = "cooldown · watch"

        CSS = """
        Screen { layout: vertical; }
        Header { dock: top; }
        Footer { dock: bottom; }

        /* Healthbar — slim horizontal strip with a real background tint
           so it reads as a designed band rather than another line of
           tightly-packed text. Two-col padding gives the Health pill
           air on both sides and matches the body grid's outer padding. */
        #healthbar {
            dock: top;
            height: 1;
            padding: 0 2;
            background: $boost;
            color: $text;
        }

        #body {
            layout: grid;
            grid-size: 2 4;
            grid-rows: auto auto 1fr 1fr;
            grid-gutter: 1 2;
            padding: 1 2;
            height: 1fr;
        }

        /* Default panel — quiet muted border, generous inner padding.
           Border colour comes from $surface-lighten-2 (not $primary) so
           the four info panels visually recede until you focus one.
           Info panels size to their content (height: auto) so empty
           space under Thermal/Battery flows to the tables instead of
           leaving dead air. Tables still get height: 1fr via grid-rows
           (set on #body) so they fill the remaining vertical space. */
        .panel {
            border: round $surface-lighten-2;
            padding: 0 1;
            height: auto;
            min-height: 6;
        }
        DataTable.panel {
            height: 1fr;
        }
        .panel:focus-within {
            border: round $accent-lighten-1;
        }
        /* Interactive tables get the accent border so the user knows
           they're tab-targetable, but kept slimmer than the focused
           state. */
        DataTable.panel {
            border: round $accent 50%;
        }
        DataTable.panel > .datatable--cursor {
            background: $accent 35%;
        }
        DataTable.panel > .datatable--header {
            text-style: bold;
            color: $text-muted;
        }
        DataTable.panel:hover {
            border: round $accent-lighten-1;
        }
        /* Focused panel — the only visually heavy chrome on screen.
           Combination of heavy border, soft fill, and a bolder cursor
           row mirrors the lazygit/k9s focus feedback. */
        DataTable:focus.panel {
            border: heavy $accent;
            background: $accent 6%;
        }
        DataTable:focus.panel > .datatable--cursor {
            background: $accent 60%;
            text-style: bold;
        }
        DataTable:focus.panel > .datatable--header {
            text-style: bold;
            color: $accent-lighten-2;
        }

        /* Ports gets the full bottom row — wide tables read much better
           than narrow ones when attribution columns pile up. */
        #ports {
            column-span: 2;
        }

        /* Footer — match the healthbar's $boost background so the top
           and bottom strips frame the panel grid symmetrically. Key
           letters get accent + bold for k9s-style affordance; the
           description text dims to $text-muted so the key is what the
           eye lands on, not the verb. */
        Footer {
            background: $boost;
            color: $text;
        }
        FooterKey > .footer-key--key {
            background: $accent;
            color: $background;
            text-style: bold;
        }
        FooterKey > .footer-key--description {
            color: $text-muted;
        }
        FooterKey:hover > .footer-key--key {
            background: $accent-lighten-1;
        }
        FooterKey.-command-palette {
            color: $text-muted;
        }
        """

        # Footer is intentionally lean — only the 6 keys a user actually
        # reaches for during a normal session show in the help bar. The
        # rest (force-kill, panel focus shortcuts, tick-rate tuning) stay
        # bound but hidden so power users discover them via docs/README
        # rather than visual clutter.
        BINDINGS = [
            Binding("q", "quit", "Quit"),
            Binding("r", "refresh_fast", "Refresh"),
            Binding("p", "toggle_pause", "Pause"),
            Binding("d", "toggle_dry_run", "Dry-run"),
            Binding("k", "kill_selected", "Kill"),
            Binding("?", "show_help", "Help"),
            Binding("R", "refresh_slow", "Refresh slow", show=False),
            Binding("K", "kill_selected_force", "Force kill", show=False),
            Binding("1", "focus_ai", "AI table", show=False),
            Binding("2", "focus_projects", "Projects", show=False),
            Binding("3", "focus_ports", "Ports", show=False),
            Binding("plus,equals_sign", "faster_fast", "Faster", show=False),
            Binding("minus,underscore", "slower_fast", "Slower", show=False),
            Binding("bracket_left", "faster_slow", "Slow+", show=False),
            Binding("bracket_right", "slower_slow", "Slow-", show=False),
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
            # Rolling trend buffers for the CPU / Memory sparklines (last
            # ~30 fast ticks ≈ 1.5 minutes at the default 3 s cadence).
            self._cpu_hist: deque[float] = deque(maxlen=30)
            self._mem_hist: deque[float] = deque(maxlen=30)

        # ---------------------------------------------------------- compose
        def compose(self):
            # Boot states use a shared loading glyph + per-panel hint so
            # the very first frame of the dashboard reads as designed
            # (not "broken / no data") in the ~3 seconds before the
            # fast tick fires. Consistent ◌ across panels gives the
            # loading state a unified visual rhythm.
            def _boot(hint: str) -> str:
                return f"\n  [dim]◌  {hint}[/]"

            # No default Header — the custom healthbar (below) is the
            # designed top strip. Eliminates the two-band stack that
            # the default Header(show_clock=True) used to create and
            # reclaims 1 row of vertical real estate for panel content.
            yield Static(
                "  [dim]◌  cool watch · warming up…[/]",
                id="healthbar",
                markup=True,
            )
            cpu = Static(_boot("reading CPU…"), id="cpu", classes="panel")
            cpu.border_title = "CPU"
            mem = Static(_boot("reading memory…"), id="mem", classes="panel")
            mem.border_title = "Memory"
            therm = Static(_boot("reading thermal state…"), id="thermal", classes="panel")
            therm.border_title = "Thermal"
            batt = Static(_boot("reading battery…"), id="battery", classes="panel")
            batt.border_title = "Battery"
            ai = DataTable(id="ai", classes="panel", cursor_type="row", zebra_stripes=True)
            # Title carries the noun; subtitle carries the action hint.
            # Subtitle renders bottom-right by default, so the kill hint
            # is findable without competing with the panel name for
            # weight at the top.
            ai.border_title = "AI CLI Inventory"
            ai.border_subtitle = "[dim]focus + k to kill[/]"
            proj = DataTable(id="projects", classes="panel", cursor_type="row", zebra_stripes=True)
            proj.border_title = "Top Projects by RSS"
            proj.border_subtitle = "[dim]focus + k to kill[/]"
            ports = DataTable(id="ports", classes="panel", cursor_type="row", zebra_stripes=True)
            ports.border_title = "Listening Ports"
            ports.border_subtitle = "[dim]focus + k to kill[/]"
            yield Grid(cpu, mem, therm, batt, ai, proj, ports, id="body")
            yield Footer()

        # ---------------------------------------------------------- mount
        def on_mount(self) -> None:
            # Header labels — uppercased + dim so the header recedes and
            # the data values become the visual figure. Numeric headers
            # also right-justify so they sit above their right-aligned
            # column values instead of floating at the left edge.
            def _h(text: str) -> Text:
                return Text(text.upper(), style="bold dim")

            def _hr(text: str) -> Text:
                return Text(text.upper(), style="bold dim", justify="right")

            # Configure the DataTables once.
            ai: DataTable = self.query_one("#ai", DataTable)
            # Column names mirror `cool status` so the two views share
            # vocabulary: "total RSS" / "total CPU%" make it explicit
            # these are sums across the group, not per-process values.
            ai.add_columns(
                _h("kind"), _hr("count"), _hr("total RSS"),
                _hr("total CPU%"), _hr("idle (max)"),
            )
            proj: DataTable = self.query_one("#projects", DataTable)
            # LANGS column dropped — at half-grid width the table was
            # overflowing and chopping LAUNCHER chips to 2 chars. The
            # lang info is low-signal during live monitoring; users who
            # need it can run `cool dev`. Folding launchers into the
            # freed space restores readable chip rendering.
            proj.add_columns(
                _h("project"), _hr("count"), _hr("total RSS"),
                _h("launchers"),
            )
            ports: DataTable = self.query_one("#ports", DataTable)
            ports.add_columns(
                _hr("port"), _h("proto"), _hr("pid"),
                _h("process"), _h("project"), _h("launcher"),
            )

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
                log.exception("watch fast-tick: cpu collector failed")
                self.call_from_thread(self._set_error, "cpu", exc)
            try:
                mem = mem_mod.collect()
                self.call_from_thread(self._apply_mem, mem)
            except Exception as exc:  # noqa: BLE001
                log.exception("watch fast-tick: memory collector failed")
                self.call_from_thread(self._set_error, "mem", exc)
            try:
                therm = therm_mod.collect()
                self.call_from_thread(self._apply_thermal, therm)
            except Exception as exc:  # noqa: BLE001
                log.exception("watch fast-tick: thermal collector failed")
                self.call_from_thread(self._set_error, "thermal", exc)
            try:
                batt = batt_mod.collect()
                self.call_from_thread(self._apply_battery, batt)
            except Exception as exc:  # noqa: BLE001
                log.exception("watch fast-tick: battery collector failed")
                self.call_from_thread(self._set_error, "battery", exc)
            try:
                procs = procs_mod.collect(sample_interval=0.1)
                procs_mod.enrich_idle(procs)
                procs.sort(key=lambda p: -p.rss)
                ai_rows = build_ai_rows(procs)
                self.call_from_thread(self._apply_ai, procs, ai_rows)
            except Exception as exc:  # noqa: BLE001
                log.exception("watch fast-tick: procs collector failed")
                self.call_from_thread(self._set_table_error, "ai", exc)

        def _gather_slow(self) -> None:
            try:
                devs = dev_mod.collect(sample_interval=0.1)
                rows = build_project_rows(devs)
                self.call_from_thread(self._apply_projects, rows)
            except Exception as exc:  # noqa: BLE001
                log.exception("watch slow-tick: projects panel failed")
                self.call_from_thread(self._set_table_error, "projects", exc)
            try:
                entries = ports_mod.collect()
                launchers, projects = _attribute_ports({e.pid for e in entries})
                rows = build_port_rows(entries, launchers, projects)
                self.call_from_thread(self._apply_ports, rows)
            except Exception as exc:  # noqa: BLE001
                log.exception("watch slow-tick: ports panel failed")
                self.call_from_thread(self._set_table_error, "ports", exc)

        # ---------------------------------------------------------- apply (UI thread)
        def _apply_cpu(self, sys_stats: sys_mod.SystemStats) -> None:
            self._sys = sys_stats
            self._updated["cpu"] = time.time()
            self._cpu_hist.append(sys_stats.cpu_percent)
            cpu_w = self.query_one("#cpu", Static)
            cpu_w.update(_cpu_content(sys_stats, history=list(self._cpu_hist)))
            cpu_w.border_title = _cpu_title_summary(sys_stats)
            self._refresh_subtitle()

        def _apply_mem(self, mem: mem_mod.MemoryStats) -> None:
            self._mem = mem
            self._updated["mem"] = time.time()
            self._mem_hist.append(mem.used_percent)
            mem_w = self.query_one("#mem", Static)
            mem_w.update(_mem_content(mem, history=list(self._mem_hist)))
            mem_w.border_title = _mem_title_summary(mem)
            self._refresh_subtitle()

        def _apply_thermal(self, therm: therm_mod.ThermalStats) -> None:
            self._therm = therm
            self._updated["thermal"] = time.time()
            therm_w = self.query_one("#thermal", Static)
            therm_w.update(_thermal_content(therm))
            therm_w.border_title = _thermal_title_summary(therm)
            self._refresh_subtitle()

        def _apply_battery(self, batt: batt_mod.BatteryStats | None) -> None:
            self._batt = batt
            self._updated["battery"] = time.time()
            batt_w = self.query_one("#battery", Static)
            batt_w.update(_battery_content(batt))
            batt_w.border_title = _battery_title_summary(batt)
            self._refresh_subtitle()

        def _apply_ai(self, procs: list[ProcInfo], rows: list[AiRow]) -> None:
            self._procs = procs
            self._ai_rows = rows
            self._updated["ai"] = time.time()
            t: DataTable = self.query_one("#ai", DataTable)
            t.clear()
            if not rows:
                # Empty state: no claude/codex/droid/tmux processes right
                # now. Show a single helper row so the table doesn't look
                # broken on a freshly-rebooted Mac.
                t.add_row(
                    "[dim italic]no sessions[/]",
                    "[dim]–[/]",
                    "[dim]–[/]",
                    "[dim]–[/]",
                    "[dim italic]launch claude / codex / droid …[/]",
                )
                t.border_title = "AI CLI Inventory"
                t.border_subtitle = "[dim]empty[/]"
                self._refresh_subtitle()
                return
            # Numeric cells get right-justified Text so values stack at
            # the decimal/unit instead of drifting left. Strings stay as
            # raw markup strings — DataTable handles them fine.
            def _rj(value: str) -> Text:
                return Text.from_markup(value, justify="right")

            for row in rows:
                color = _kind_color(row.kind)
                idle_clr = _idle_color(row.idle)
                # Colour lives on the dot only — letting the family
                # glyph carry identification and keeping the kind name
                # at neutral bold makes a row of 6+ kinds read calm
                # instead of confetti-coloured.
                # Idle duration gets severity colour so long-idle
                # (= reapable by `cool reap`) rows surface visibly
                # without reading any numbers.
                t.add_row(
                    f"[{color}]●[/] [bold]{row.kind}[/]",
                    _rj(str(row.count)),
                    _rj(human_bytes(row.rss)),
                    _rj(f"{row.cpu:.1f}"),
                    _rj(f"[{idle_clr}]{human_duration(row.idle)}[/]"),
                )
            # Title carries the headline aggregate (procs + RSS); the
            # kill-key hint moves to the subtitle where it sits quietly
            # at the bottom-right.
            total_rss = sum(r.rss for r in rows)
            total = sum(r.count for r in rows)
            t.border_title = (
                f"AI CLI Inventory  [dim]· {total} procs · "
                f"{human_bytes(total_rss)}[/]"
            )
            t.border_subtitle = "[dim]k to kill kind[/]"
            self._refresh_subtitle()

        def _apply_projects(self, rows: list[ProjectRow]) -> None:
            self._project_rows = rows
            self._updated["projects"] = time.time()
            t: DataTable = self.query_one("#projects", DataTable)
            t.clear()
            if not rows:
                t.add_row(
                    "[dim italic]no dev processes[/]",
                    "[dim]–[/]",
                    "[dim]–[/]",
                    "[dim italic]open a project with node / python / …[/]",
                )
                t.border_title = "Top Projects by RSS"
                t.border_subtitle = "[dim]empty[/]"
                return
            for row in rows:
                name_cell = _decorate_project_name(row.name, orphan=row.orphan)
                t.add_row(
                    name_cell,
                    Text(str(row.count), justify="right"),
                    Text(human_bytes(row.rss), justify="right"),
                    _chip_tokens(row.launchers),
                )
            total_rss = sum(r.rss for r in rows)
            t.border_title = (
                f"Top Projects by RSS  [dim]· {len(rows)} shown · "
                f"{human_bytes(total_rss)}[/]"
            )
            t.border_subtitle = "[dim]k to kill project[/]"

        def _apply_ports(self, rows: list[PortRow]) -> None:
            self._port_rows = rows
            self._updated["ports"] = time.time()
            t: DataTable = self.query_one("#ports", DataTable)
            t.clear()
            if not rows:
                t.add_row(
                    "[dim italic]no listeners[/]",
                    "[dim]–[/]",
                    "[dim]–[/]",
                    "[dim]–[/]",
                    "[dim]–[/]",
                    "[dim italic]nothing is listening on a TCP port[/]",
                )
                t.border_title = "Listening Ports"
                t.border_subtitle = "[dim]empty[/]"
                return
            for row in rows:
                t.add_row(
                    Text(str(row.port), justify="right"),
                    row.proto,
                    Text(str(row.pid), justify="right"),
                    row.process,
                    row.project,
                    _chip_tokens(row.launcher),
                )
            t.border_title = f"Listening Ports  [dim]· {len(rows)} shown[/]"
            t.border_subtitle = "[dim]k to kill pid[/]"

        def _set_error(self, panel_id: str, exc: BaseException) -> None:
            with contextlib.suppress(Exception):
                self.query_one(f"#{panel_id}", Static).update(
                    f"[red]collector error[/]\n[dim]{type(exc).__name__}: {exc}[/]"
                )

        def _set_table_error(self, panel_id: str, exc: BaseException) -> None:
            # Overwrite (rather than append to) both title and subtitle:
            # consecutive failed ticks were previously stacking
            # "· error: X  · error: Y  · error: Z …" until a successful
            # tick reset the title. Now title resets every error, and
            # the kill-hint subtitle is replaced with the error type so
            # the bottom-right slot doesn't go stale during outages.
            base = {
                "ai": "AI CLI Inventory",
                "projects": "Top Projects by RSS",
                "ports": "Listening Ports",
            }.get(panel_id, panel_id)
            with contextlib.suppress(Exception):
                t = self.query_one(f"#{panel_id}", DataTable)
                t.clear()
                t.border_title = base
                t.border_subtitle = f"[bold red]✗ {type(exc).__name__}[/]"

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
        def action_show_help(self) -> None:
            """Pop a transient Toast listing every binding, so the lean
            footer stays scannable without orphaning the advanced keys."""
            lines = [
                "[bold]Refresh[/]  r · R (slow)",
                "[bold]Tables[/]   1 AI  ·  2 Projects  ·  3 Ports",
                "[bold]Kill[/]     k SIGTERM  ·  K SIGKILL",
                "[bold]Tick[/]     + / -  fast ±1s   ·   [ / ]  slow ±5s",
                "[bold]Mode[/]     p Pause   ·   d Dry-run",
            ]
            self.notify("\n".join(lines), title="cool watch — keys", timeout=8.0)

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

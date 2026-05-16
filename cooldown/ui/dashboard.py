"""`cool status` one-shot dashboard (Rich, mimicking Mole's layout)."""
from __future__ import annotations

import json
import platform
from dataclasses import asdict, is_dataclass
from typing import Any

from rich.box import SIMPLE
from rich.columns import Columns
from rich.console import Console, Group
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from ..collectors import battery as batt_mod
from ..collectors import memory as mem_mod
from ..collectors import procs as procs_mod
from ..collectors import system as sys_mod
from ..collectors import thermal as therm_mod
from ..util import bar, human_bytes, human_duration, sparkline

# ---------------------------------------------------------------------------
# Severity colour policy (keep in lock-step across all panels)
# ---------------------------------------------------------------------------
#   ok / normal / safe        → green
#   notable / active / accent → cyan          (only for the "active but
#                                              not stressed" mid-band)
#   warn / approaching limit  → yellow        (plain, never bold)
#   critical / outlier / hot  → bold red      (only place where bold +
#                                              red combine — reserves
#                                              that weight for trouble)
#
# Health-score colour uses the same scale, just compressed because it's
# already a 0–100 abstraction rather than a raw percent.

def _pct_color(pct: float) -> str:
    if pct >= 90:
        return "bold red"
    if pct >= 75:
        return "yellow"
    if pct >= 50:
        return "cyan"
    return "green"


# ---------------------------------------------------------------------------
# AI CLI family colour palette (shared with `cool watch`)
# ---------------------------------------------------------------------------
# Each kind gets a stable colour so a glance at the inventory tells you
# "the claude block is the chunky one this morning" without reading any
# names. Colours follow vendor cues where there's a recognisable brand
# (Anthropic-ish magenta, OpenAI-ish green, Google-ish blue, GitHub
# yellow, Cursor cyan). Multiplexer kinds get a desaturated colour so
# they sit visually behind the AI CLIs.
KIND_COLORS: dict[str, str] = {
    # Anthropic / Factory / agent-driven CLIs
    "claude": "bright_magenta",
    "droid": "bright_blue",
    "hermes": "bright_cyan",
    # OpenAI / Google / Microsoft families
    "codex": "bright_green",
    "gemini": "blue",
    "copilot": "bright_yellow",
    # Cursor / IDE-attached agents
    "cursor-agent": "cyan",
    "windsurf": "bright_magenta",
    "continue": "magenta",
    "amp": "magenta",
    # Specialists
    "aider": "red",
    "opencode": "bright_red",
    "nanobot": "bright_yellow",
    "qwen": "yellow",
    "kimi": "yellow",
    "goose": "bright_white",
    "aichat": "white",
    "crush": "bright_red",
    # Multiplexers — desaturated to sit behind the AI CLIs
    "tmux": "dim cyan",
    "cmux": "dim cyan",
    "zellij": "dim cyan",
}


def kind_color(kind: str) -> str:
    return KIND_COLORS.get(kind, "yellow")


# ---------------------------------------------------------------------------
# Top Projects name decoration (shared with `cool watch`)
# ---------------------------------------------------------------------------
# The project bucket name from dev.collect() can be a real project path
# (``search-boss``), or one of the synthesised fallback buckets
# ``(npx: …)`` / ``(app: …)`` / ``(vscode: …)`` / ``(orphan)`` /
# ``(background: …)``. We replace the wordy parenthesised prefix with a
# single icon glyph + colour so:
#   - real projects (the ones a user actually owns) read bold and stand
#     out vs the surrounding system noise
#   - synthetic buckets are visually clustered by category, dim-by-default
#   - long names (npx package paths, MCP server names) truncate cleanly
#     with an ellipsis instead of wrapping onto the next row.

BUCKET_ICONS: dict[str, tuple[str, str]] = {
    # prefix → (icon, colour)
    "npx":        ("◈", "dim cyan"),
    "app":        ("▣", "dim yellow"),
    "vscode":     ("⊟", "dim magenta"),
    "tool":       ("⊙", "dim"),
    "background": ("▸", "dim"),
}


def decorate_project_name(name: str, *, max_width: int = 32, orphan: bool = False) -> str:
    """Render a project bucket name with an icon + truncation.

    Real project names stay bold; synthesised buckets get an icon
    matching their fallback category and a dim colour so they sit
    visually behind the user's actual repos.
    """
    icon: str | None = None
    color: str = "bold"
    if name == "(orphan)":
        icon, color = "⚠", "red"
        body = "orphan"
    elif name.startswith("(") and name.endswith(")") and ":" in name:
        prefix, rest = name[1:-1].split(":", 1)
        meta = BUCKET_ICONS.get(prefix.strip())
        if meta is not None:
            icon, color = meta
            body = rest.strip()
        else:
            body = name
    else:
        body = name

    if orphan and icon is None:
        # Real on-disk project but all procs are orphans — surface the
        # signal without losing the bold project-name treatment.
        icon, color = "⚠", "bold red"

    # Reserve 2 cols for the icon + space when one is present.
    body_budget = max_width - (2 if icon else 0)
    if len(body) > body_budget:
        body = body[: max(1, body_budget - 1)] + "…"

    if icon:
        return f"[{color}]{icon}[/] [{color}]{body}[/]"
    return f"[{color}]{body}[/]"


def _kv(rows: list[tuple[str, str]]) -> Table:
    t = Table.grid(padding=(0, 1))
    t.add_column(style="dim", justify="right")
    t.add_column()
    for k, v in rows:
        t.add_row(k, v)
    return t


def _cpu_content(
    sys_stats: sys_mod.SystemStats,
    *,
    history: list[float] | None = None,
) -> Table:
    """Inner CPU content (no outer Panel). Shared with `cool watch`.

    Per-core breakdown is the headline so the user can spot a single
    runaway core immediately — a 95% P-core inside a 48% average is the
    signature of a thermal bottleneck and wouldn't surface from the total
    alone. When ``history`` is supplied (recent total-CPU samples), a
    unicode sparkline is rendered next to the current value so trends
    "rising / falling / flat" are visible at a glance.
    """
    from ..collectors import hostinfo  # local import: breaks circular edge
    pct = sys_stats.cpu_percent
    color = _pct_color(pct)
    if history:
        spark = sparkline(history, hi=100.0, width=20)
        total_cell = (
            f"[{color}]{bar(pct)} {pct:5.1f}%[/]  [dim]{spark}[/]"
        )
    else:
        total_cell = f"[{color}]{bar(pct)} {pct:5.1f}%[/]"
    rows: list[tuple[str, str]] = [
        ("Total", total_cell),
    ]
    host = hostinfo.collect()
    per = sys_stats.per_cpu
    if per:
        p_end = min(host.perf_cores or len(per), len(per))
        if p_end:
            p_avg = sum(per[:p_end]) / p_end
            p_max = max(per[:p_end])
            rows.append((
                "P-cores",
                f"[{_pct_color(p_avg)}]{bar(p_avg)} avg {p_avg:5.1f}%[/]  "
                f"max [{_pct_color(p_max)}]{p_max:5.1f}%[/]  "
                f"(×{p_end})",
            ))
        if p_end < len(per):
            e = per[p_end:]
            e_avg = sum(e) / len(e)
            e_max = max(e)
            rows.append((
                "E-cores",
                f"[{_pct_color(e_avg)}]{bar(e_avg)} avg {e_avg:5.1f}%[/]  "
                f"max [{_pct_color(e_max)}]{e_max:5.1f}%[/]  "
                f"(×{len(e)})",
            ))
        # Top-3 hottest individual cores, Mole-style. Surfaces "Core 5 pinned
        # at 100%" which otherwise disappears inside the P/E average.
        ranked = sorted(enumerate(per), key=lambda iv: iv[1], reverse=True)
        for idx, val in ranked[:3]:
            label = f"P{idx + 1}" if idx < p_end else f"E{idx - p_end + 1}"
            rows.append((
                f"Core {label}",
                f"[{_pct_color(val)}]{bar(val)} {val:5.1f}%[/]",
            ))
    rows.append((
        "Load",
        f"{sys_stats.load_1:.2f} / {sys_stats.load_5:.2f} / {sys_stats.load_15:.2f}"
        + (f"  [dim]{sys_stats.topology}[/]" if sys_stats.topology else ""),
    ))
    rows.append(("Uptime", human_duration(sys_stats.uptime)))
    rows.append(("Processes", str(sys_stats.total_processes)))
    return _kv(rows)


def _cpu_panel(sys_stats: sys_mod.SystemStats) -> Panel:
    return Panel(_cpu_content(sys_stats), title="[bold]CPU[/]", box=SIMPLE, border_style="blue")


def _mem_content(
    mem: mem_mod.MemoryStats,
    *,
    history: list[float] | None = None,
) -> Table:
    used_pct = mem.used_percent
    color = _pct_color(used_pct)
    swap_pct = (mem.swap_used / mem.swap_total * 100.0) if mem.swap_total else 0.0
    swap_color = _pct_color(swap_pct)
    used_cell = (
        f"[{color}]{bar(used_pct)} {used_pct:5.1f}%[/]  "
        f"{human_bytes(mem.used)} / {human_bytes(mem.total)}"
    )
    if history:
        used_cell += f"  [dim]{sparkline(history, hi=100.0, width=20)}[/]"
    return _kv(
        [
            (
                "Used",
                used_cell,
            ),
            ("Avail", human_bytes(mem.available)),
            ("Wired", human_bytes(mem.wired)),
            (
                "Compressed",
                # Compressed memory is one of macOS's main responses to
                # pressure; once it climbs past ~25% of total RAM you're
                # already paying a CPU tax. Surface the ratio inline so
                # users see "26.3GB (41%)" instead of just a raw byte
                # count that doesn't mean much on its own.
                f"{human_bytes(mem.compressed)}"
                + (
                    f"  [dim]({mem.compressed / mem.total * 100:.0f}%)[/]"
                    if mem.total
                    else ""
                ),
            ),
            (
                "Swap",
                f"[{swap_color}]{bar(swap_pct)} {swap_pct:5.1f}%[/]  "
                f"{human_bytes(mem.swap_used)} / {human_bytes(mem.swap_total)}"
                if mem.swap_total
                else "unused",
            ),
            ("Pressure", _pressure_badge(mem.pressure_level)),
        ]
    )


def _mem_panel(mem: mem_mod.MemoryStats) -> Panel:
    return Panel(
        _mem_content(mem), title="[bold]Memory[/]", box=SIMPLE, border_style="magenta"
    )


def _pressure_badge(level: str) -> str:
    mapping = {
        "normal": "[green]normal[/]",
        "warn": "[yellow]warn[/]",
        "critical": "[bold red]critical[/]",
    }
    return mapping.get(level, "[dim]unknown[/]")


def _thermal_content(t: therm_mod.ThermalStats) -> Table:
    """Thermal / power summary.

    Every row is prefixed with a colour-coded status glyph so the eye
    can scan a single column (green ● / yellow ◆ / red ▲) to spot
    trouble before reading any of the values.
    """
    def _ok(text: str) -> str:
        return f"[green]●[/]  [green]{text}[/]"

    def _warn(text: str) -> str:
        return f"[yellow]◆[/]  [yellow]{text}[/]"

    def _crit(text: str) -> str:
        return f"[bold red]▲[/]  [bold red]{text}[/]"

    def _dim(text: str) -> str:
        return f"[dim]○[/]  [dim]{text}[/]"

    warning_cell = _ok("none") if t.thermal_warning == "none" else _crit(t.thermal_warning)

    if "throttled" in (t.cpu_power_status or ""):
        cpu_cell = _crit(t.cpu_power_status)
    elif (t.cpu_power_status or "").lower() == "normal":
        cpu_cell = _ok("normal")
    else:
        cpu_cell = _dim(t.cpu_power_status or "?")

    lowpower_cell = _warn("on") if t.low_power_mode else _ok("off")

    pct = f"{t.battery_percent}%" if t.battery_percent is not None else ""
    if t.ac_power:
        power_cell = _ok(f"AC {pct}".rstrip())
    elif t.battery_percent is not None and t.battery_percent < 20:
        power_cell = _warn(f"battery {pct}")
    else:
        power_cell = _dim(f"battery {pct}".rstrip())

    def _sleep_cell(minutes: int | None) -> str:
        if minutes is None:
            return _dim("?")
        if minutes == 0:
            return _crit("never")
        return _ok(f"{minutes} min")

    sleep_state_cell = _crit("prevented") if t.sleep_prevented else _ok("allowed")

    rows = [
        ("Warning", warning_cell),
        ("CPU power", cpu_cell),
        ("Low power", lowpower_cell),
        ("Power src", power_cell),
        ("Display sleep", _sleep_cell(t.display_sleep)),
        ("Disk sleep", _sleep_cell(t.disk_sleep)),
        ("Sleep state", sleep_state_cell),
    ]
    return _kv(rows)


def _thermal_panel(t: therm_mod.ThermalStats) -> Panel:
    return Panel(
        _thermal_content(t), title="[bold]Thermal / Power[/]", box=SIMPLE, border_style="red"
    )


def _battery_content(b: batt_mod.BatteryStats | None) -> Table:
    """Battery cell details — capacity, cycles, temp, charge state.

    Temperature belongs on the *first line* here rather than in Thermal
    because cell temperature is what actually wears the battery out and is
    what users on 'cool-down-my-mac' typically care about when the laptop
    gets hot.
    """
    if b is None:
        # Empty state: desktop Macs (Mac mini / Studio / Pro) and Macs
        # plugged into a Studio Display have no battery. Surface that
        # explicitly so the otherwise-blank panel doesn't look broken.
        return _kv(
            [
                ("○", "[dim]no battery detected[/]"),
                ("", "[dim italic]desktop or display-only setup[/]"),
            ]
        )

    rows: list[tuple[str, str]] = []
    if b.percent is not None:
        color = "green" if b.percent >= 40 else "yellow" if b.percent >= 15 else "bold red"
        pct_cell = f"[{color}]{bar(b.percent)} {b.percent:5.1f}%[/]"
        if b.fully_charged:
            pct_cell += "  [dim green]charged[/]"
        elif b.charging:
            pct_cell += "  [dim green]charging[/]"
        elif b.ac_attached:
            pct_cell += "  [dim]on AC[/]"
        else:
            pct_cell += "  [dim yellow]on battery[/]"
        rows.append(("Level", pct_cell))

    if b.temp_c is not None:
        temp_color = (
            "bold red" if b.temp_c >= 40 else "yellow" if b.temp_c >= 35 else "green"
        )
        rows.append(("Temp", f"[{temp_color}]{b.temp_c:.1f}°C[/]"))

    if b.health_percent is not None:
        h = b.health_percent
        h_color = "green" if h >= 85 else "yellow" if h >= 70 else "bold red"
        rows.append(("Health", f"[{h_color}]{h:.1f}%[/]"))

    if b.cycle_count is not None:
        # Apple rates most batteries for 1000 cycles — warn past 800.
        c_color = "green" if b.cycle_count < 600 else "yellow" if b.cycle_count < 900 else "bold red"
        rows.append(("Cycles", f"[{c_color}]{b.cycle_count}[/]"))

    bits: list[str] = []
    if b.power_w is not None and abs(b.power_w) > 0.05:
        sign = "+" if b.charging and b.power_w > 0 else ""
        bits.append(f"{sign}{b.power_w:.1f}W")
    if b.minutes_remaining is not None:
        h, m = divmod(b.minutes_remaining, 60)
        bits.append(f"{h}h{m:02d}m" if h else f"{m}m")
    if bits:
        rows.append(("Flow", "  ·  ".join(bits)))

    return _kv(rows)


def _battery_panel(b: batt_mod.BatteryStats | None) -> Panel:
    return Panel(
        _battery_content(b), title="[bold]Battery[/]", box=SIMPLE, border_style="green"
    )


def _cli_panel(procs: list[procs_mod.ProcInfo]) -> Panel:
    groups = procs_mod.group_by_kind(procs)
    if not groups:
        return Panel(
            Text("no AI CLIs / multiplexers detected", style="dim"),
            title="[bold]AI CLI Inventory[/]",
            box=SIMPLE,
            border_style="yellow",
        )

    table = Table(box=None, expand=True, show_edge=False)
    table.add_column("kind", style="bold")
    table.add_column("count", justify="right")
    table.add_column("total RSS", justify="right")
    table.add_column("total CPU%", justify="right")
    table.add_column("idle (max)", justify="right")

    grand_total_procs = 0
    grand_total_rss = 0
    for kind, items in groups.items():
        total_rss = sum(p.rss for p in items)
        total_cpu = sum(p.cpu_percent for p in items)
        max_idle = max((p.idle_seconds or 0.0) for p in items)
        # Use the same per-family palette `cool watch` uses so a user
        # bouncing between the two views never sees claude rendered in
        # two different colours.
        color = kind_color(kind)
        table.add_row(
            f"[{color}]●[/] [{color}]{kind}[/]",
            str(len(items)),
            human_bytes(total_rss),
            f"{total_cpu:.1f}",
            human_duration(max_idle),
        )
        grand_total_procs += len(items)
        grand_total_rss += total_rss
    # Mirror `cool watch`'s pattern: surface the fleet aggregates in the
    # panel title so the user doesn't need to scan + sum the rows to
    # answer "how heavy is my AI CLI fleet right now?".
    title = (
        f"[bold]AI CLI Inventory[/]  [dim]· {grand_total_procs} procs · "
        f"{human_bytes(grand_total_rss)}[/]"
    )
    return Panel(table, title=title, box=SIMPLE, border_style="yellow")


def _health_score(
    mem: mem_mod.MemoryStats,
    sys_stats: sys_mod.SystemStats,
    t: therm_mod.ThermalStats,
    battery: batt_mod.BatteryStats | None = None,
) -> tuple[int, str]:
    score = 100
    # macOS reports a kernel-level memory pressure_level that is the
    # ground truth — it incorporates compression and page-in rate, both
    # of which can be high even when used_percent looks "fine" (e.g.
    # 76% used but 36% of RAM is compressed → kernel says critical).
    # Prefer it when available; fall back to raw used_percent only when
    # the kernel signal is missing.
    if mem.pressure_level == "critical":
        score -= 25
    elif mem.pressure_level == "warn":
        score -= 12
    elif mem.pressure_level not in ("normal", "warn", "critical"):
        if mem.used_percent >= 90:
            score -= 25
        elif mem.used_percent >= 80:
            score -= 12
    if mem.swap_total and mem.swap_used / mem.swap_total > 0.5:
        score -= 15
    if sys_stats.cpu_percent >= 80:
        score -= 15
    elif sys_stats.cpu_percent >= 60:
        score -= 6
    if t.thermal_warning != "none":
        score -= 20
    if t.sleep_prevented and t.display_sleep == 0:
        score -= 5
    # Battery cell temperature is THE signal this tool exists to surface
    # — without it the headline Health score can stay at 100 while the
    # laptop is too hot to hold. Use thresholds that match the colour
    # scale on the Battery panel (35°C warn / 40°C hot / 45°C critical).
    if battery is not None and battery.temp_c is not None:
        if battery.temp_c >= 45:
            score -= 20
        elif battery.temp_c >= 40:
            score -= 10
        elif battery.temp_c >= 35:
            score -= 3
    score = max(0, min(100, score))
    # Return base colour names (no bold prefix); callers can compose
    # ``[bold {color}]`` themselves. This avoids the "bold bold red"
    # marker that pops up when the colour is wrapped at the call site.
    if score >= 80:
        color = "green"
    elif score >= 55:
        color = "yellow"
    else:
        color = "red"
    return score, color


def render(console: Console | None = None) -> None:
    console = console or Console()
    with console.status("[dim]sampling...[/]", spinner="dots"):
        sys_stats = sys_mod.collect()
        mem = mem_mod.collect()
        therm = therm_mod.collect()
        procs = procs_mod.collect()
        procs_mod.enrich_idle(procs)
        # Battery temperature is one of the headline cooldown signals; the
        # collector returns None on desktop Macs (Mac mini / Studio / Pro),
        # in which case the panel renders an explicit "no battery" empty
        # state instead of being omitted entirely.
        try:
            batt = batt_mod.collect()
        except Exception:  # noqa: BLE001
            batt = None

    score, score_color = _health_score(mem, sys_stats, therm, batt)
    header_bits = [
        "[bold]cooldown[/] status",
        f"Health [bold {score_color}]● {score}[/]",
        f"[dim]{platform.node()}[/] · {platform.machine()} · macOS {platform.mac_ver()[0]}",
    ]
    console.print(Text("  ").join(Text.from_markup(b) for b in header_bits))
    console.print()

    # Two layouts depending on terminal width:
    #   ≥ 120 cols → 4-up column row matching `cool watch`'s top half
    #   < 120 cols → vertical stack so each panel keeps a readable width
    panels = [
        _cpu_panel(sys_stats),
        _mem_panel(mem),
        _thermal_panel(therm),
        _battery_panel(batt),
    ]
    if console.size.width >= 120:
        console.print(Columns(panels, equal=True, expand=True))
    else:
        for panel in panels:
            console.print(panel)
    console.print(_cli_panel(procs))
    console.print(_dev_panel())

    # Actionable advice block. Print every hint that applies, in
    # descending severity, so a user with three simultaneous problems
    # sees all three (the previous if/elif chain hid everything past the
    # first match).
    hints: list[str] = []
    if mem.pressure_level == "critical" or (
        mem.swap_total and mem.swap_used / mem.swap_total > 0.7
    ):
        hints.append(
            "[bold red]![/] memory pressure critical — run "
            "[cyan]cool procs[/] or [cyan]cool reap[/] to recover"
        )
    if therm.thermal_warning and therm.thermal_warning != "none":
        hints.append(
            f"[bold red]![/] thermal warning [bold red]{therm.thermal_warning}[/] — "
            "close GUI hogs with [cyan]cool apps suspend[/] or quit heavy AI CLIs"
        )
    if therm.sleep_prevented:
        hints.append(
            "[yellow]![/] sleep is being prevented — run "
            "[cyan]cool thermal --restore[/] to reset displaysleep / disksleep"
        )
    if batt is not None and batt.temp_c is not None and batt.temp_c >= 40:
        hints.append(
            f"[yellow]![/] battery cell hot ({batt.temp_c:.1f}°C) — "
            "give the laptop a few minutes off charge / heavy load"
        )
    if any(
        p.kind in procs_mod.AI_KINDS and (p.idle_seconds or 0) > 1800 for p in procs
    ):
        hints.append(
            "[yellow]hint:[/] idle AI CLI sessions detected — try "
            "[cyan]cool reap --dry-run[/]"
        )
    for hint in hints:
        console.print(hint)


def _as_jsonable(obj: Any) -> Any:
    """Recursively convert dataclasses + Paths into JSON-friendly forms."""
    if is_dataclass(obj) and not isinstance(obj, type):
        return {k: _as_jsonable(v) for k, v in asdict(obj).items()}
    if isinstance(obj, dict):
        return {k: _as_jsonable(v) for k, v in obj.items()}
    if isinstance(obj, list | tuple):
        return [_as_jsonable(v) for v in obj]
    if hasattr(obj, "__fspath__"):  # pathlib.Path
        return str(obj)
    return obj


def render_json(console: Console | None = None) -> None:
    """Machine-readable equivalent of ``render()`` for scripting."""
    console = console or Console()
    sys_stats = sys_mod.collect()
    mem = mem_mod.collect()
    therm = therm_mod.collect()
    procs = procs_mod.collect()
    procs_mod.enrich_idle(procs)
    try:
        batt = batt_mod.collect()
    except Exception:  # noqa: BLE001
        batt = None
    score, _ = _health_score(mem, sys_stats, therm, batt)
    payload = {
        "health_score": score,
        "host": {
            "node": platform.node(),
            "machine": platform.machine(),
            "macos": platform.mac_ver()[0],
        },
        "system": _as_jsonable(sys_stats),
        "memory": _as_jsonable(mem),
        "thermal": _as_jsonable(therm),
        "battery": _as_jsonable(batt) if batt is not None else None,
        "procs": [_as_jsonable(p) for p in procs],
    }
    console.print_json(json.dumps(payload, default=str))


def render_group(mem: mem_mod.MemoryStats, sys_stats: sys_mod.SystemStats) -> Group:
    """Expose a Group for reuse (e.g., future `cool watch`)."""
    return Group(_cpu_panel(sys_stats), _mem_panel(mem))


def _dev_panel(limit: int = 5) -> Panel:
    """Top projects by RSS. Imported lazily so `cool status` still runs if
    the dev collector is missing or fails."""
    try:
        from ..collectors import dev as dev_mod  # noqa: PLC0415
        devs = dev_mod.collect(sample_interval=0.1)
    except Exception:  # noqa: BLE001
        return Panel(
            Text("dev collector unavailable", style="dim"),
            title="[bold]Top Projects by RSS[/]",
            box=SIMPLE,
            border_style="cyan",
        )

    groups = dev_mod.group_by(devs, "project")
    if not groups:
        return Panel(
            Text("no dev processes detected", style="dim"),
            title="[bold]Top Projects by RSS[/]",
            box=SIMPLE,
            border_style="cyan",
        )

    table = Table(box=None, expand=True, show_edge=False)
    # No fixed style on the "project" column — the cell markup from
    # decorate_project_name() already carries the right colour (bold for
    # real projects, dim-by-category for synthetic buckets).
    table.add_column("project")
    table.add_column("count", justify="right")
    table.add_column("total RSS", justify="right")
    table.add_column("langs", style="dim")
    table.add_column("launchers", style="dim")

    ranked = sorted(
        groups.items(),
        key=lambda kv: -sum(d.rss for d in kv[1]),
    )[:limit]
    shown_total_rss = 0
    for name, items in ranked:
        total_rss = sum(d.rss for d in items)
        langs = ",".join(sorted({d.lang for d in items}))
        launchers = ",".join(sorted({d.launcher.kind for d in items}))
        orphan = any(d.is_orphan for d in items)
        # Use the same bucket-icon + truncation as `cool watch` so the
        # one-shot status view matches the live dashboard exactly.
        name_cell = decorate_project_name(name, orphan=orphan)
        table.add_row(
            name_cell,
            str(len(items)),
            human_bytes(total_rss),
            langs,
            launchers,
        )
        shown_total_rss += total_rss
    title = (
        f"[bold]Top Projects by RSS[/]  [dim]· {len(ranked)} shown · "
        f"{human_bytes(shown_total_rss)}[/]"
    )
    return Panel(table, title=title, box=SIMPLE, border_style="cyan")

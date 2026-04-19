"""`cool status` one-shot dashboard (Rich, mimicking Mole's layout)."""
from __future__ import annotations

import platform

from rich.box import SIMPLE
from rich.columns import Columns
from rich.console import Console, Group
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from ..collectors import memory as mem_mod
from ..collectors import procs as procs_mod
from ..collectors import system as sys_mod
from ..collectors import thermal as therm_mod
from ..util import bar, human_bytes, human_duration


def _pct_color(pct: float) -> str:
    if pct >= 90:
        return "bold red"
    if pct >= 75:
        return "bold yellow"
    if pct >= 50:
        return "cyan"
    return "green"


def _kv(rows: list[tuple[str, str]]) -> Table:
    t = Table.grid(padding=(0, 1))
    t.add_column(style="dim", justify="right")
    t.add_column()
    for k, v in rows:
        t.add_row(k, v)
    return t


def _cpu_content(sys_stats: sys_mod.SystemStats) -> Table:
    """Inner CPU content (no outer Panel). Shared with `cool watch`."""
    pct = sys_stats.cpu_percent
    color = _pct_color(pct)
    return _kv(
        [
            ("Total", f"[{color}]{bar(pct)} {pct:5.1f}%[/]"),
            (
                "Load",
                f"{sys_stats.load_1:.2f} / {sys_stats.load_5:.2f} / {sys_stats.load_15:.2f}"
                f"  ({sys_stats.cpu_count_logical} cores)",
            ),
            ("Uptime", human_duration(sys_stats.uptime)),
            ("Processes", str(sys_stats.total_processes)),
        ]
    )


def _cpu_panel(sys_stats: sys_mod.SystemStats) -> Panel:
    return Panel(_cpu_content(sys_stats), title="[bold]CPU[/]", box=SIMPLE, border_style="blue")


def _mem_content(mem: mem_mod.MemoryStats) -> Table:
    used_pct = mem.used_percent
    color = _pct_color(used_pct)
    swap_pct = (mem.swap_used / mem.swap_total * 100.0) if mem.swap_total else 0.0
    swap_color = _pct_color(swap_pct)
    return _kv(
        [
            (
                "Used",
                f"[{color}]{bar(used_pct)} {used_pct:5.1f}%[/]  "
                f"{human_bytes(mem.used)} / {human_bytes(mem.total)}",
            ),
            ("Avail", human_bytes(mem.available)),
            ("Wired", human_bytes(mem.wired)),
            ("Compressed", human_bytes(mem.compressed)),
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
    rows = [
        ("Warning", "[green]none[/]" if t.thermal_warning == "none" else f"[red]{t.thermal_warning}[/]"),
        ("CPU power", t.cpu_power_status),
        ("Low power", "[yellow]on[/]" if t.low_power_mode else "[green]off[/]"),
        (
            "Power src",
            f"[green]AC[/]  {t.battery_percent}%" if t.ac_power else f"[yellow]Battery[/]  {t.battery_percent}%",
        ),
        (
            "Display sleep",
            f"{t.display_sleep}min" if t.display_sleep else ("[red]never[/]" if t.display_sleep == 0 else "?"),
        ),
        (
            "Disk sleep",
            f"{t.disk_sleep}min" if t.disk_sleep else ("[red]never[/]" if t.disk_sleep == 0 else "?"),
        ),
        (
            "Sleep state",
            "[red]prevented[/]" if t.sleep_prevented else "[green]allowed[/]",
        ),
    ]
    return _kv(rows)


def _thermal_panel(t: therm_mod.ThermalStats) -> Panel:
    return Panel(
        _thermal_content(t), title="[bold]Thermal / Power[/]", box=SIMPLE, border_style="red"
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

    for kind, items in groups.items():
        total_rss = sum(p.rss for p in items)
        total_cpu = sum(p.cpu_percent for p in items)
        max_idle = max((p.idle_seconds or 0.0) for p in items)
        style = "yellow" if kind in procs_mod.AI_KINDS else "cyan"
        table.add_row(
            f"[{style}]{kind}[/]",
            str(len(items)),
            human_bytes(total_rss),
            f"{total_cpu:.1f}",
            human_duration(max_idle),
        )
    return Panel(table, title="[bold]AI CLI Inventory[/]", box=SIMPLE, border_style="yellow")


def _health_score(
    mem: mem_mod.MemoryStats, sys_stats: sys_mod.SystemStats, t: therm_mod.ThermalStats
) -> tuple[int, str]:
    score = 100
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
    score = max(0, min(100, score))
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

    score, score_color = _health_score(mem, sys_stats, therm)
    header_bits = [
        "[bold]cooldown[/] status",
        f"Health [{score_color}]● {score}[/]",
        f"[dim]{platform.node()}[/] · {platform.machine()} · macOS {platform.mac_ver()[0]}",
    ]
    console.print(Text("  ").join(Text.from_markup(b) for b in header_bits))
    console.print()

    panels = [_cpu_panel(sys_stats), _mem_panel(mem), _thermal_panel(therm)]
    if console.size.width >= 120:
        console.print(Columns(panels, equal=True, expand=True))
    else:
        for panel in panels:
            console.print(panel)
    console.print(_cli_panel(procs))
    console.print(_dev_panel())

    if mem.pressure_level == "critical" or (mem.swap_total and mem.swap_used / mem.swap_total > 0.7):
        console.print(
            "[bold red]![/] memory pressure critical — run [cyan]cool procs[/] or [cyan]cool reap[/] to recover"
        )
    elif any(
        p.kind in procs_mod.AI_KINDS and (p.idle_seconds or 0) > 1800 for p in procs
    ):
        console.print(
            "[yellow]hint:[/] idle AI CLI sessions detected — try [cyan]cool reap --dry-run[/]"
        )


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
    table.add_column("project", style="bold cyan")
    table.add_column("count", justify="right")
    table.add_column("total RSS", justify="right")
    table.add_column("langs", style="dim")
    table.add_column("launchers", style="dim")

    ranked = sorted(
        groups.items(),
        key=lambda kv: -sum(d.rss for d in kv[1]),
    )[:limit]
    for name, items in ranked:
        total_rss = sum(d.rss for d in items)
        langs = ",".join(sorted({d.lang for d in items}))
        launchers = ",".join(sorted({d.launcher.kind for d in items}))
        style_name = "[red]" + name + "[/]" if any(d.is_orphan for d in items) else name
        table.add_row(
            style_name,
            str(len(items)),
            human_bytes(total_rss),
            langs,
            launchers,
        )
    return Panel(table, title="[bold]Top Projects by RSS[/]", box=SIMPLE, border_style="cyan")

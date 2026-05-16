"""`cool thermal` — thermal dashboard + optional sleep-policy restore."""
from __future__ import annotations

import json
from dataclasses import asdict, is_dataclass

from rich.box import SIMPLE
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from ..actions import sleep_policy as sleep_mod
from ..collectors import thermal as therm_mod
from ..collectors import thermal_smc as smc_mod
from ..safety.confirm import confirm


def _kv(rows: list[tuple[str, str]]) -> Table:
    t = Table.grid(padding=(0, 1))
    t.add_column(style="dim", justify="right")
    t.add_column()
    for k, v in rows:
        t.add_row(k, v)
    return t


def _fmt_temp(v: float | None) -> str:
    if v is None:
        return "[dim]-[/]"
    color = "green"
    if v >= 90:
        color = "bold red"
    elif v >= 75:
        color = "red"
    elif v >= 60:
        color = "yellow"
    return f"[{color}]{v:.1f}°C[/]"


def _fmt_watts(v: float | None) -> str:
    return f"{v:.2f}W" if v is not None else "[dim]-[/]"


def _fmt_rpm(v: float | None) -> str:
    return f"{int(v)} rpm" if v is not None else "[dim]-[/]"


def _pmset_panel(t: therm_mod.ThermalStats) -> Panel:
    rows = [
        ("Warning", "[green]none[/]" if t.thermal_warning == "none" else f"[red]{t.thermal_warning}[/]"),
        ("CPU power", t.cpu_power_status),
        ("Low power", "[yellow]on[/]" if t.low_power_mode else "[green]off[/]"),
        (
            "Power src",
            (f"[green]AC[/]  {t.battery_percent}%" if t.ac_power
             else f"[yellow]Battery[/]  {t.battery_percent}%"),
        ),
        (
            "Sleep state",
            "[red]prevented[/]" if t.sleep_prevented else "[green]allowed[/]",
        ),
    ]
    return Panel(_kv(rows), title="[bold]pmset[/]", box=SIMPLE, border_style="red")


def _smc_panel(s: smc_mod.SmcReading) -> Panel:
    if s.source == "unavailable":
        body = _kv(
            [
                ("status", "[yellow]unavailable[/] — powermetrics needs root"),
                ("hint", "add a sudoers.d snippet (see below) or run `sudo -v`"),
            ]
        )
        return Panel(body, title="[bold]SMC[/]", box=SIMPLE, border_style="yellow")
    rows = [
        ("CPU die", _fmt_temp(s.cpu_die_temp)),
        ("GPU die", _fmt_temp(s.gpu_die_temp)),
        ("Fan", _fmt_rpm(s.fan_rpm)),
        ("CPU power", _fmt_watts(s.cpu_power_w)),
        ("GPU power", _fmt_watts(s.gpu_power_w)),
        ("Package", _fmt_watts(s.package_power_w)),
    ]
    return Panel(_kv(rows), title="[bold]SMC[/]", box=SIMPLE, border_style="blue")


def _policy_panel(p: sleep_mod.SleepPolicy) -> Panel:
    def _mins(v: int) -> str:
        if v < 0:
            return "[dim]?[/]"
        if v == 0:
            return "[red]never[/]"
        return f"{v} min"

    rows = [
        ("Display sleep", _mins(p.displaysleep)),
        ("Disk sleep", _mins(p.disksleep)),
        ("Power nap", "[yellow]on[/]" if p.powernap else "[green]off[/]"),
    ]
    return Panel(_kv(rows), title="[bold]Sleep policy[/]", box=SIMPLE, border_style="magenta")


def _recommendation(
    t: therm_mod.ThermalStats,
    s: smc_mod.SmcReading,
    p: sleep_mod.SleepPolicy,
) -> str:
    hints: list[str] = []
    if t.sleep_prevented:
        hints.append("an assertion is keeping the Mac awake — inspect with `pmset -g assertions`")
    if t.ac_power and (p.displaysleep == 0 or p.disksleep == 0):
        hints.append(
            "display/disk sleep disabled on AC — run `cool thermal --restore` to bring back the 10-min default"
        )
    if s.cpu_die_temp is not None and s.cpu_die_temp >= 90:
        hints.append("CPU die > 90°C — consider `cool reap` to shed idle AI workloads")
    if t.thermal_warning != "none":
        hints.append(f"thermal warning active ({t.thermal_warning}) — system is throttling")
    if not hints:
        hints.append("thermal state looks clean")
    return "  ".join("• " + h for h in hints)


def run(
    console: Console,
    *,
    restore: bool = False,
    dry_run: bool = False,
    assume_yes: bool = False,
    json_out: bool = False,
) -> int:
    with console.status("[dim]sampling thermal + power...[/]", spinner="dots"):
        t = therm_mod.collect()
        s = smc_mod.collect()
        p = sleep_mod.current()

    if json_out:
        payload = {
            "pmset": asdict(t) if is_dataclass(t) else t,
            "smc": asdict(s) if is_dataclass(s) else s,
            "sleep_policy": asdict(p) if is_dataclass(p) else p,
        }
        console.print_json(json.dumps(payload, default=str))
        return 0

    console.print(_pmset_panel(t))
    console.print(_smc_panel(s))
    console.print(_policy_panel(p))
    console.print(_recommendation(t, s, p))

    if s.source == "unavailable":
        console.print()
        console.print(
            Panel(
                smc_mod.sudoers_hint(),
                title="[bold]enable powermetrics without a password[/]",
                border_style="yellow",
                box=SIMPLE,
            )
        )

    if not restore:
        return 0

    console.print()
    msg = "Restore macOS sleep defaults (displaysleep=10, disksleep=10, powernap=off) on AC?"
    if not confirm(msg, default=False, assume_yes=assume_yes):
        console.print("[dim]cancelled[/]")
        return 0

    outcome = sleep_mod.restore_defaults(dry_run=dry_run)
    mark = "[green]✓[/]" if outcome.ok else "[red]✗[/]"
    console.print(f"{mark} {outcome.message}")
    if outcome.ok and outcome.changed:
        console.print(_policy_panel(sleep_mod.current()))
    return 0 if outcome.ok else 1

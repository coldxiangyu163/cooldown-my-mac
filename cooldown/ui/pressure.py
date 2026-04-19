"""`cool pressure` — one-shot check or watch loop with auto actions."""
from __future__ import annotations

import time
from typing import Literal

from rich.box import SIMPLE
from rich.console import Console
from rich.table import Table
from rich.text import Text

from ..actions import notify as notify_mod
from ..actions import purge as purge_mod
from ..actions.pressure import Severity, Thresholds, Verdict, evaluate
from ..actions.reap import terminate
from ..collectors import memory as mem_mod
from ..collectors import procs as procs_mod
from ..safety.confirm import confirm
from ..safety.oplog import record
from ..util import bar, human_bytes

_COLORS: dict[Severity, str] = {
    Severity.NORMAL: "green",
    Severity.WARN: "yellow",
    Severity.CRITICAL: "red",
}


def _render_verdict(console: Console, mem: mem_mod.MemoryStats, v: Verdict) -> None:
    color = _COLORS[v.severity]
    header = Text.from_markup(
        f"[bold]pressure[/]  [{color}]●[/] {v.severity.value.upper()}   "
        f"mem used [{color}]{bar(mem.used_percent)}[/] {mem.used_percent:.1f}%"
    )
    console.print(header)

    table = Table(box=SIMPLE, show_header=True, expand=False)
    table.add_column("signal", style="bold")
    table.add_column("state")
    table.add_column("detail")
    for s in v.signals:
        sc = _COLORS[s.severity]
        table.add_row(s.kind, f"[{sc}]{s.severity.value}[/]", s.label)
    console.print(table)

    console.print(f"[bold]compressor[/] {human_bytes(mem.compressed)}   "
                  f"[bold]swap[/] {human_bytes(mem.swap_used)} / {human_bytes(mem.swap_total)}")
    for rec in v.recommendations:
        console.print(f"  • {rec}")


def _auto_act(
    console: Console,
    v: Verdict,
    *,
    auto_reap: bool,
    auto_purge: bool,
    notify: bool,
    ai_idle: int,
    dry_run: bool,
) -> None:
    if v.severity is Severity.NORMAL:
        return

    if notify:
        title = f"cooldown · {v.severity.value.upper()}"
        body = "; ".join(s.label for s in v.signals if s.severity is not Severity.NORMAL)
        notify_mod.notify(title, body or "memory pressure detected")

    if v.severity is not Severity.CRITICAL:
        return

    if auto_reap:
        with console.status("[dim]auto-reaping idle AI CLI sessions...[/]"):
            procs = procs_mod.collect()
            procs_mod.enrich_idle(procs)
            targets = [
                p
                for p in procs
                if p.kind in (procs_mod.AI_KINDS | procs_mod.MUX_KINDS)
                and (p.idle_seconds or 0) >= ai_idle
            ]
        if targets:
            outcomes = terminate(targets, dry_run=dry_run)
            ok = sum(1 for o in outcomes if o.ok)
            console.print(f"[bold]auto-reap[/]: {ok}/{len(outcomes)} terminated "
                          f"(freed ≈ {human_bytes(sum(p.rss for p in targets))})")
            record("pressure.auto-reap", severity=v.severity.value, count=len(outcomes), ok=ok)
        else:
            console.print("[dim]auto-reap: no idle targets[/]")

    if auto_purge:
        console.print("[dim]running purge...[/]")
        r = purge_mod.purge(dry_run=dry_run)
        mark = "[green]✓[/]" if r.ok else "[red]✗[/]"
        console.print(f"{mark} purge: {r.message}")
        record("pressure.auto-purge", severity=v.severity.value, ok=r.ok, message=r.message)


def run(
    console: Console,
    *,
    mode: Literal["once", "watch"] = "once",
    interval: int = 60,
    auto_reap: bool = False,
    auto_purge: bool = False,
    notify: bool = False,
    ai_idle: int = 1800,
    ram_warn: float = 0.80,
    ram_crit: float = 0.92,
    swap_warn: float = 0.40,
    swap_crit: float = 0.80,
    comp_warn: float = 0.15,
    comp_crit: float = 0.25,
    dry_run: bool = False,
    assume_yes: bool = False,
) -> int:
    th = Thresholds(
        ram_warn=ram_warn,
        ram_crit=ram_crit,
        swap_warn=swap_warn,
        swap_crit=swap_crit,
        compressor_warn=comp_warn,
        compressor_crit=comp_crit,
    )

    guard = (auto_reap or auto_purge) and mode == "once" and not assume_yes and not dry_run
    if guard and not confirm(
        "auto-reap / auto-purge may kill processes or drop disk cache. Continue?",
        default=False,
    ):
        console.print("[dim]cancelled[/]")
        return 0

    def _tick() -> Verdict:
        mem = mem_mod.collect()
        v = evaluate(mem, th)
        record(
            "pressure.eval",
            severity=v.severity.value,
            ram=mem.used_percent,
            swap_used=mem.swap_used,
            swap_total=mem.swap_total,
            compressor=mem.compressed,
        )
        _render_verdict(console, mem, v)
        _auto_act(
            console,
            v,
            auto_reap=auto_reap,
            auto_purge=auto_purge,
            notify=notify,
            ai_idle=ai_idle,
            dry_run=dry_run,
        )
        return v

    if mode == "once":
        v = _tick()
        return 0 if v.severity is not Severity.CRITICAL else 2

    console.print(f"[dim]watching every {interval}s · ctrl-c to stop[/]")
    try:
        while True:
            console.rule(time.strftime("%H:%M:%S"))
            _tick()
            time.sleep(interval)
    except KeyboardInterrupt:
        console.print("[dim]stopped[/]")
    return 0


# Watch mode is line-oriented on purpose so it stays readable in tmux/cmux
# panes and composes with `tee`.

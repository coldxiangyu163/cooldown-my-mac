"""`cool procs` — grouped AI CLI inventory + interactive multi-select kill."""
from __future__ import annotations

import json
from dataclasses import asdict

import questionary
from rich.box import SIMPLE
from rich.console import Console
from rich.table import Table

from ..actions.reap import terminate
from ..collectors import procs as procs_mod
from ..safety.confirm import confirm
from ..util import human_bytes, human_duration


def _print_table(console: Console, procs: list[procs_mod.ProcInfo]) -> None:
    if not procs:
        console.print("[dim]no AI CLI / multiplexer processes detected.[/]")
        return
    table = Table(title="AI CLI inventory", box=SIMPLE, show_lines=False)
    table.add_column("kind", style="bold yellow")
    table.add_column("pid", justify="right", style="cyan")
    table.add_column("ppid", justify="right", style="dim")
    table.add_column("rss", justify="right")
    table.add_column("cpu%", justify="right")
    table.add_column("age", justify="right")
    table.add_column("idle", justify="right")
    table.add_column("tty", style="dim")
    table.add_column("cmd")

    groups = procs_mod.group_by_kind(procs)
    for kind, items in groups.items():
        for p in items:
            idle_txt = human_duration(p.idle_seconds) if p.idle_seconds is not None else "-"
            table.add_row(
                kind,
                str(p.pid),
                str(p.ppid),
                human_bytes(p.rss),
                f"{p.cpu_percent:.1f}",
                human_duration(p.age),
                idle_txt,
                p.tty or "-",
                p.cmdline[:80],
            )
    console.print(table)


def _label(p: procs_mod.ProcInfo) -> str:
    idle_txt = human_duration(p.idle_seconds) if p.idle_seconds is not None else "?"
    cmd = p.cmdline if len(p.cmdline) <= 70 else p.cmdline[:67] + "..."
    return (
        f"[{p.kind:<7}] pid={p.pid:<6} rss={human_bytes(p.rss):>7} "
        f"cpu={p.cpu_percent:4.1f}% idle={idle_txt:<6} {cmd}"
    )


def run(
    console: Console,
    *,
    dry_run: bool = False,
    force: bool = False,
    assume_yes: bool = False,
    kind_filter: list[str] | None = None,
    json_out: bool = False,
) -> int:
    with console.status("[dim]scanning processes...[/]", spinner="dots"):
        procs = procs_mod.collect()
        procs_mod.enrich_idle(procs)

    if kind_filter:
        want = {k.lower() for k in kind_filter}
        procs = [p for p in procs if p.kind in want]

    if json_out:
        console.print_json(json.dumps([asdict(p) for p in procs], default=str))
        return 0

    _print_table(console, procs)
    if not procs:
        return 0

    try:
        picks = questionary.checkbox(
            "Select processes to terminate (space = toggle, enter = confirm):",
            choices=[
                questionary.Choice(title=_label(p), value=p, checked=False) for p in procs
            ],
        ).ask()
    except KeyboardInterrupt:
        console.print("[dim]cancelled[/]")
        return 0
    if not picks:
        console.print("[dim]nothing selected.[/]")
        return 0

    action = "DRY-RUN terminate" if dry_run else ("SIGKILL" if force else "SIGTERM")
    if not confirm(f"{action} {len(picks)} process(es)?", default=False, assume_yes=assume_yes):
        console.print("[dim]cancelled[/]")
        return 0

    outcomes = terminate(picks, dry_run=dry_run, force=force)
    ok = sum(1 for o in outcomes if o.ok)
    fail = len(outcomes) - ok
    for o in outcomes:
        mark = "[green]✓[/]" if o.ok else "[red]✗[/]"
        console.print(f"{mark} pid={o.pid:<6} {o.kind:<8} {o.message}")
    console.print(f"\n[bold]done[/]: {ok} ok, {fail} failed")
    return 0 if fail == 0 else 1

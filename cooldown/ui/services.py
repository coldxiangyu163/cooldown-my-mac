"""`cool services` — interactive start/stop of local dev services."""
from __future__ import annotations

from dataclasses import dataclass

import questionary
from rich.box import SIMPLE
from rich.console import Console
from rich.table import Table

from ..actions import services as svc_act
from ..collectors import services as svc_mod
from ..safety.confirm import confirm
from ..util import human_bytes


@dataclass
class _Task:
    svc: svc_mod.ServiceInfo
    action: str  # "start" | "stop"


def _print_table(console: Console, services: list[svc_mod.ServiceInfo]) -> None:
    if not services:
        console.print("[dim]no known dev services detected.[/]")
        return
    table = Table(title="local dev services", box=SIMPLE, show_lines=False)
    table.add_column("kind", style="bold yellow")
    table.add_column("name")
    table.add_column("status")
    table.add_column("pid", justify="right", style="cyan")
    table.add_column("rss", justify="right")
    table.add_column("cpu%", justify="right")
    table.add_column("brew", style="dim")

    for s in services:
        if s.running:
            status = "[green]running[/]"
        elif s.brew_managed:
            status = "[red]stopped[/]"
        else:
            status = "[dim]unknown[/]"
        brew = s.brew_status or ("-" if not s.brew_managed else "?")
        table.add_row(
            s.kind,
            s.name,
            status,
            str(s.pid) if s.pid else "-",
            human_bytes(s.rss) if s.rss else "-",
            f"{s.cpu_percent:.1f}" if s.cpu_percent else "-",
            brew,
        )
    console.print(table)


def _label(task: _Task) -> str:
    s = task.svc
    verb = "stop" if task.action == "stop" else "start"
    rss = human_bytes(s.rss) if s.rss else "-"
    pid = s.pid if s.pid else "-"
    return (
        f"[{verb:<5}] {s.kind:<9} {s.name:<22} pid={str(pid):<6} "
        f"rss={rss:>7} brew={s.brew_status or '-'}"
    )


def _build_tasks(services: list[svc_mod.ServiceInfo]) -> list[_Task]:
    tasks: list[_Task] = []
    for s in services:
        if s.running:
            tasks.append(_Task(s, "stop"))
        elif s.brew_managed:
            tasks.append(_Task(s, "start"))
    return tasks


def run(
    console: Console,
    *,
    dry_run: bool = False,
    assume_yes: bool = False,
    only: list[str] | None = None,
) -> int:
    with console.status("[dim]scanning dev services...[/]", spinner="dots"):
        services = svc_mod.collect()

    if only:
        wanted = {k.lower() for k in only}
        services = [s for s in services if s.kind in wanted]

    _print_table(console, services)
    if not services:
        return 0

    tasks = _build_tasks(services)
    if not tasks:
        console.print("[dim]nothing actionable (no running or brew-managed services).[/]")
        return 0

    try:
        picks: list[_Task] | None = questionary.checkbox(
            "Select services to toggle (space = pick, enter = confirm):",
            choices=[
                questionary.Choice(title=_label(t), value=t, checked=False) for t in tasks
            ],
        ).ask()
    except KeyboardInterrupt:
        console.print("[dim]cancelled[/]")
        return 0
    if not picks:
        console.print("[dim]nothing selected.[/]")
        return 0

    verb = "DRY-RUN" if dry_run else "APPLY"
    if not confirm(
        f"{verb} {len(picks)} service change(s)?", default=False, assume_yes=assume_yes
    ):
        console.print("[dim]cancelled[/]")
        return 0

    outcomes: list[svc_act.ServiceOutcome] = []
    for task in picks:
        if task.action == "stop":
            outcomes.append(svc_act.stop(task.svc, dry_run=dry_run))
        else:
            outcomes.append(svc_act.start(task.svc, dry_run=dry_run))

    ok = sum(1 for o in outcomes if o.ok)
    fail = len(outcomes) - ok
    for o in outcomes:
        mark = "[green]✓[/]" if o.ok else "[red]✗[/]"
        console.print(f"{mark} {o.action:<5} {o.name:<22} {o.message}")
    console.print(f"\n[bold]done[/]: {ok} ok, {fail} failed")
    return 0 if fail == 0 else 1

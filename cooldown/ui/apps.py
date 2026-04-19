"""`cool apps` — list / suspend / resume / quit heavy background apps."""
from __future__ import annotations

import questionary
from rich.box import SIMPLE
from rich.console import Console
from rich.table import Table

from ..actions import apps as app_act
from ..collectors import apps as apps_mod
from ..safety.confirm import confirm
from ..util import human_bytes

_VALID_ACTIONS = {"list", "suspend", "resume", "quit"}


def _print_table(console: Console, apps: list[apps_mod.AppInfo]) -> None:
    if not apps:
        console.print("[dim]no heavy apps detected.[/]")
        return
    table = Table(title="heavy apps", box=SIMPLE, show_lines=False)
    table.add_column("kind", style="bold yellow")
    table.add_column("name")
    table.add_column("pid", justify="right", style="cyan")
    table.add_column("ppid", justify="right", style="dim")
    table.add_column("rss", justify="right")
    table.add_column("cpu%", justify="right")
    table.add_column("state")

    for a in apps:
        state = "[blue]frozen?[/]" if a.frozen else "[green]active[/]"
        table.add_row(
            a.kind,
            a.display_name,
            str(a.pid),
            str(a.ppid),
            human_bytes(a.rss),
            f"{a.cpu_percent:.1f}",
            state,
        )
    console.print(table)


def _label(a: apps_mod.AppInfo) -> str:
    return (
        f"[{a.kind:<8}] {a.display_name:<12} pid={a.pid:<6} "
        f"rss={human_bytes(a.rss):>7} cpu={a.cpu_percent:4.1f}%"
    )


def run(
    console: Console,
    *,
    action: str,
    dry_run: bool = False,
    assume_yes: bool = False,
    kinds: list[str] | None = None,
) -> int:
    if action not in _VALID_ACTIONS:
        console.print(f"[red]unknown action:[/] {action}")
        return 2

    with console.status("[dim]scanning heavy apps...[/]", spinner="dots"):
        apps = apps_mod.collect()

    if kinds:
        wanted = {k.lower() for k in kinds}
        apps = [a for a in apps if a.kind in wanted]

    _print_table(console, apps)
    if action == "list":
        return 0

    if not apps:
        return 0

    # If kinds were given, we skip the interactive picker and act on all
    # matching apps. Otherwise prompt the user.
    if kinds:
        picks: list[apps_mod.AppInfo] = apps
    else:
        try:
            picks = (
                questionary.checkbox(
                    f"Select apps to {action} (space = pick, enter = confirm):",
                    choices=[
                        questionary.Choice(title=_label(a), value=a, checked=False)
                        for a in apps
                    ],
                ).ask()
                or []
            )
        except KeyboardInterrupt:
            console.print("[dim]cancelled[/]")
            return 0

    if not picks:
        console.print("[dim]nothing selected.[/]")
        return 0

    verb = f"DRY-RUN {action}" if dry_run else action.upper()
    if not confirm(
        f"{verb} {len(picks)} app(s)?", default=False, assume_yes=assume_yes
    ):
        console.print("[dim]cancelled[/]")
        return 0

    outcomes: list[app_act.AppActionOutcome] = []
    for a in picks:
        if action == "suspend":
            outcomes.append(app_act.suspend(a, dry_run=dry_run))
        elif action == "resume":
            outcomes.append(app_act.resume(a, dry_run=dry_run))
        else:  # quit
            outcomes.append(app_act.quit_app(a, dry_run=dry_run))

    ok = sum(1 for o in outcomes if o.ok)
    fail = len(outcomes) - ok
    for o in outcomes:
        mark = "[green]✓[/]" if o.ok else "[red]✗[/]"
        console.print(f"{mark} {o.action:<7} {o.kind:<8} pid={o.pid:<6} {o.message}")
    console.print(f"\n[bold]done[/]: {ok} ok, {fail} failed")
    return 0 if fail == 0 else 1

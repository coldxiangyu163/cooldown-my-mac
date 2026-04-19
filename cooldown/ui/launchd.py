"""`cool launchd` — audit + interactively disable launchd jobs."""
from __future__ import annotations

import questionary
from rich.box import SIMPLE
from rich.console import Console
from rich.table import Table

from ..actions.launchd import disable as disable_action
from ..collectors import launchd as launchd_mod
from ..safety.confirm import confirm

_CATEGORY_STYLE: dict[launchd_mod.Category, str] = {
    "apple": "dim",
    "homebrew": "cyan",
    "third-party": "yellow",
    "user": "green",
    "unknown": "magenta",
}


def _summary(console: Console, entries: list[launchd_mod.LaunchdEntry]) -> None:
    groups = launchd_mod.group_by_category(entries)
    t = Table(title=f"launchd jobs ({len(entries)} total)", box=SIMPLE, show_lines=False)
    t.add_column("category", style="bold")
    t.add_column("count", justify="right")
    t.add_column("running", justify="right")
    t.add_column("example", style="dim")
    for cat in ("apple", "homebrew", "third-party", "user", "unknown"):
        items = groups.get(cat, [])  # type: ignore[arg-type]
        if not items:
            continue
        running = sum(1 for e in items if e.pid is not None)
        example = items[0].label if items else ""
        style = _CATEGORY_STYLE.get(cat, "white")  # type: ignore[arg-type]
        t.add_row(f"[{style}]{cat}[/]", str(len(items)), str(running), example)
    console.print(t)


def _suspicious_table(
    console: Console, entries: list[launchd_mod.LaunchdEntry], limit: int
) -> None:
    s = launchd_mod.suspicious(entries)[:limit]
    if not s:
        console.print("[green]no suspicious entries[/]")
        return
    t = Table(title=f"suspicious (top {len(s)})", box=SIMPLE)
    t.add_column("label")
    t.add_column("category")
    t.add_column("pid", justify="right")
    t.add_column("exit", justify="right")
    t.add_column("path", style="dim")
    for e in s:
        style = _CATEGORY_STYLE.get(e.category, "white")
        t.add_row(
            e.label,
            f"[{style}]{e.category}[/]",
            str(e.pid) if e.pid is not None else "-",
            str(e.last_exit_status) if e.last_exit_status is not None else "-",
            e.path or "-",
        )
    console.print(t)


def _entry_label(e: launchd_mod.LaunchdEntry) -> str:
    pid = f"pid={e.pid}" if e.pid is not None else "pid=-"
    rc = f"exit={e.last_exit_status}" if e.last_exit_status is not None else "exit=-"
    return f"[{e.category:<11}] {pid:<9} {rc:<7} {e.label}"


def _audit(
    console: Console,
    entries: list[launchd_mod.LaunchdEntry],
    *,
    category: str | None,
    dry_run: bool,
    assume_yes: bool,
) -> int:
    # Never surface Apple-owned agents in the disable picker.
    selectable = [e for e in entries if e.category != "apple"]
    if category:
        selectable = [e for e in selectable if e.category == category]
    if not selectable:
        console.print("[dim]nothing to audit in that scope.[/]")
        return 0

    t = Table(title=f"audit candidates ({len(selectable)})", box=SIMPLE)
    t.add_column("label")
    t.add_column("category")
    t.add_column("pid", justify="right")
    t.add_column("exit", justify="right")
    t.add_column("path", style="dim")
    for e in selectable:
        style = _CATEGORY_STYLE.get(e.category, "white")
        t.add_row(
            e.label,
            f"[{style}]{e.category}[/]",
            str(e.pid) if e.pid is not None else "-",
            str(e.last_exit_status) if e.last_exit_status is not None else "-",
            e.path or "-",
        )
    console.print(t)

    try:
        picks = questionary.checkbox(
            "Select launchd jobs to disable (bootout):",
            choices=[
                questionary.Choice(title=_entry_label(e), value=e, checked=False)
                for e in selectable
            ],
        ).ask()
    except KeyboardInterrupt:
        console.print("[dim]cancelled[/]")
        return 0
    if not picks:
        console.print("[dim]nothing selected[/]")
        return 0

    verb = "DRY-RUN bootout" if dry_run else "bootout"
    if not confirm(f"{verb} {len(picks)} launchd job(s)?", default=False, assume_yes=assume_yes):
        console.print("[dim]cancelled[/]")
        return 0

    outcomes = [disable_action(e, dry_run=dry_run) for e in picks]
    ok = sum(1 for o in outcomes if o.ok)
    for o in outcomes:
        mark = "[green]✓[/]" if o.ok else "[red]✗[/]"
        console.print(f"{mark} {o.label}  {o.message}")
    console.print(f"\n[bold]done[/]: {ok}/{len(outcomes)} booted out")
    return 0 if ok == len(outcomes) else 1


def run(
    console: Console,
    *,
    audit: bool = False,
    disable: bool = False,
    dry_run: bool = False,
    assume_yes: bool = False,
    category: str | None = None,
) -> int:
    with console.status("[dim]listing launchd jobs...[/]", spinner="dots"):
        entries = launchd_mod.collect()

    if not entries:
        console.print("[yellow]launchctl list returned no entries[/]")
        return 0

    _summary(console, entries)
    _suspicious_table(console, entries, limit=10)

    if audit or disable:
        console.print()
        return _audit(
            console,
            entries,
            category=category,
            dry_run=dry_run,
            assume_yes=assume_yes,
        )
    return 0

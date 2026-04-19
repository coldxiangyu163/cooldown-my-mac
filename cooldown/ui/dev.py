"""`cool dev` — dev-stack (node/python/ruby/...) process inventory.

Presents a project / lang / launcher / framework grouped view, with an
optional interactive multi-select kill flow that reuses the same safety
machinery (self-protection + op-log) as ``cool procs`` / ``cool reap``.
"""
from __future__ import annotations

import questionary
from rich.box import SIMPLE
from rich.console import Console
from rich.table import Table

from ..actions.reap import terminate
from ..collectors import dev as dev_mod
from ..collectors.dev import DevProc
from ..collectors.procs import ProcInfo
from ..safety.confirm import confirm
from ..util import human_bytes, human_duration

_GROUP_DIMS = {"project", "lang", "launcher", "framework"}


def _truncate(text: str, width: int = 80) -> str:
    if len(text) <= width:
        return text
    return text[: width - 1] + "…"


def _kind_cell(dev: DevProc) -> str:
    lang = dev.lang
    if dev.is_orphan:
        return f"[red]{lang} [ORPHAN][/red]"
    if dev.framework:
        return f"{lang}/{dev.framework}"
    return lang


def _summary(devs: list[DevProc]) -> str:
    totals: dict[str, int] = {}
    total_rss = 0
    for d in devs:
        totals[d.lang] = totals.get(d.lang, 0) + 1
        total_rss += d.rss
    lang_bits = " ".join(f"{k}={v}" for k, v in sorted(totals.items(), key=lambda kv: -kv[1]))
    return (
        f"{len(devs)} dev processes  ·  total RSS {human_bytes(total_rss)}  ·  "
        f"languages: {lang_bits or '(none)'}"
    )


def _build_table(devs: list[DevProc], by: str) -> Table:
    title = f"dev inventory · grouped by {by}"
    table = Table(title=title, box=SIMPLE, show_lines=False)

    if by == "project":
        table.add_column("project", style="bold magenta")
        table.add_column("pid", justify="right", style="cyan")
        table.add_column("kind", style="yellow")
        table.add_column("rss", justify="right")
        table.add_column("cpu%", justify="right")
        table.add_column("idle", justify="right")
        table.add_column("launcher", style="dim")
        table.add_column("cmd")
    elif by == "lang":
        table.add_column("lang", style="bold yellow")
        table.add_column("pid", justify="right", style="cyan")
        table.add_column("rss", justify="right")
        table.add_column("cpu%", justify="right")
        table.add_column("project", style="magenta")
        table.add_column("launcher", style="dim")
        table.add_column("cmd")
    elif by == "launcher":
        table.add_column("launcher", style="bold cyan")
        table.add_column("pid", justify="right", style="cyan")
        table.add_column("lang", style="yellow")
        table.add_column("rss", justify="right")
        table.add_column("cpu%", justify="right")
        table.add_column("project", style="magenta")
        table.add_column("cmd")
    else:  # framework
        table.add_column("framework", style="bold green")
        table.add_column("pid", justify="right", style="cyan")
        table.add_column("lang", style="yellow")
        table.add_column("rss", justify="right")
        table.add_column("cpu%", justify="right")
        table.add_column("project", style="magenta")
        table.add_column("cmd")

    groups = dev_mod.group_by(devs, by)
    for header, items in groups.items():
        for d in items:
            idle_txt = human_duration(d.idle_seconds) if d.idle_seconds is not None else "-"
            proj_name = d.project.name if d.project else dev_mod._group_key(d, "project")
            cmd = _truncate(d.cmdline, 80)
            if by == "project":
                table.add_row(
                    header,
                    str(d.pid),
                    _kind_cell(d),
                    human_bytes(d.rss),
                    f"{d.cpu_percent:.1f}",
                    idle_txt,
                    d.launcher.label,
                    cmd,
                )
            elif by == "lang":
                table.add_row(
                    header,
                    str(d.pid),
                    human_bytes(d.rss),
                    f"{d.cpu_percent:.1f}",
                    proj_name,
                    d.launcher.label,
                    cmd,
                )
            elif by == "launcher":
                table.add_row(
                    header,
                    str(d.pid),
                    _kind_cell(d),
                    human_bytes(d.rss),
                    f"{d.cpu_percent:.1f}",
                    proj_name,
                    cmd,
                )
            else:  # framework
                table.add_row(
                    header,
                    str(d.pid),
                    _kind_cell(d),
                    human_bytes(d.rss),
                    f"{d.cpu_percent:.1f}",
                    proj_name,
                    cmd,
                )
    return table


def _label(dev: DevProc) -> str:
    idle_txt = human_duration(dev.idle_seconds) if dev.idle_seconds is not None else "?"
    proj_name = dev.project.name if dev.project else dev_mod._group_key(dev, "project")
    cmd = dev.cmdline if len(dev.cmdline) <= 60 else dev.cmdline[:57] + "..."
    orphan = " [ORPHAN]" if dev.is_orphan else ""
    return (
        f"[{dev.lang:<6}{orphan}] pid={dev.pid:<6} rss={human_bytes(dev.rss):>7} "
        f"cpu={dev.cpu_percent:4.1f}% idle={idle_txt:<6} "
        f"proj={proj_name[:18]:<18} via={dev.launcher.label[:10]:<10} {cmd}"
    )


def _to_procinfo(dev: DevProc) -> ProcInfo:
    """Adapt a DevProc into a ProcInfo for the shared ``terminate`` path."""
    return ProcInfo(
        pid=dev.pid,
        ppid=dev.ppid,
        kind=dev.lang,
        name=dev.name,
        cmdline=dev.cmdline,
        rss=dev.rss,
        cpu_percent=dev.cpu_percent,
        create_time=0.0,
        age=dev.age,
        tty=None,
        user=dev.user,
        idle_seconds=dev.idle_seconds,
    )


def _apply_filters(
    devs: list[DevProc],
    *,
    lang: list[str] | None,
    project_filter: list[str] | None,
    launcher: list[str] | None,
) -> list[DevProc]:
    out = devs
    if lang:
        want = {x.lower() for x in lang}
        out = [d for d in out if d.lang in want]
    if project_filter:
        needles = [x.lower() for x in project_filter]
        out = [
            d
            for d in out
            if d.project is not None
            and any(n in d.project.name.lower() for n in needles)
        ]
    if launcher:
        want_l = {x.lower() for x in launcher}
        out = [d for d in out if d.launcher.kind in want_l]
    return out


def run(
    console: Console,
    *,
    by: str = "project",
    stale_only: bool = False,
    lang: list[str] | None = None,
    project_filter: list[str] | None = None,
    launcher: list[str] | None = None,
    kill: bool = False,
    dry_run: bool = False,
    force: bool = False,
    assume_yes: bool = False,
) -> int:
    if by not in _GROUP_DIMS:
        console.print(f"[red]invalid --by value[/]: {by!r} (must be one of {sorted(_GROUP_DIMS)})")
        return 2

    with console.status("[dim]scanning dev processes...[/]", spinner="dots"):
        devs = dev_mod.collect()
        dev_mod.enrich_idle(devs)

    devs = _apply_filters(devs, lang=lang, project_filter=project_filter, launcher=launcher)
    if stale_only:
        devs = dev_mod.stale(devs)

    if not devs:
        console.print("[dim]no matching dev processes.[/]")
        return 0

    console.print(f"[bold]cool dev[/] — {_summary(devs)}")
    console.print(_build_table(devs, by))

    if not kill:
        return 0

    try:
        picks = questionary.checkbox(
            "Select dev processes to terminate (space = toggle, enter = confirm):",
            choices=[questionary.Choice(title=_label(d), value=d, checked=False) for d in devs],
        ).ask()
    except KeyboardInterrupt:
        console.print("[dim]cancelled[/]")
        return 0
    if not picks:
        console.print("[dim]nothing selected.[/]")
        return 0

    action = "DRY-RUN terminate" if dry_run else ("SIGKILL" if force else "SIGTERM")
    if not confirm(
        f"{action} {len(picks)} dev process(es)?",
        default=False,
        assume_yes=assume_yes,
    ):
        console.print("[dim]cancelled[/]")
        return 0

    proc_targets = [_to_procinfo(d) for d in picks]
    outcomes = terminate(proc_targets, dry_run=dry_run, force=force)
    ok = sum(1 for o in outcomes if o.ok)
    fail = len(outcomes) - ok
    for o in outcomes:
        mark = "[green]✓[/]" if o.ok else "[red]✗[/]"
        console.print(f"{mark} pid={o.pid:<6} {o.kind:<8} {o.message}")
    console.print(f"\n[bold]done[/]: {ok} ok, {fail} failed")
    return 0 if fail == 0 else 1

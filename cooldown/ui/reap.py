"""`cool reap` — automatic idle-session culling."""
from __future__ import annotations

from rich.box import SIMPLE
from rich.console import Console
from rich.table import Table

from ..actions.reap import terminate
from ..collectors import procs as procs_mod
from ..safety.confirm import confirm
from ..util import human_bytes, human_duration

DEFAULT_AI_IDLE = 1800  # 30 min
DEFAULT_MUX_IDLE = 14400  # 4 h


def _candidates(
    procs: list[procs_mod.ProcInfo],
    ai_idle: int,
    mux_idle: int,
    kinds: list[str] | None,
) -> list[procs_mod.ProcInfo]:
    out: list[procs_mod.ProcInfo] = []
    wanted = {k.lower() for k in kinds} if kinds else None
    for p in procs:
        if wanted and p.kind not in wanted:
            continue
        threshold = ai_idle if p.kind in procs_mod.AI_KINDS else mux_idle
        if p.kind in procs_mod.AI_KINDS | procs_mod.MUX_KINDS and (p.idle_seconds or 0) >= threshold:
            out.append(p)
    return out


def run(
    console: Console,
    *,
    ai_idle: int = DEFAULT_AI_IDLE,
    mux_idle: int = DEFAULT_MUX_IDLE,
    dry_run: bool = False,
    force: bool = False,
    assume_yes: bool = False,
    kinds: list[str] | None = None,
) -> int:
    with console.status("[dim]scanning for idle sessions...[/]", spinner="dots"):
        procs = procs_mod.collect()
        procs_mod.enrich_idle(procs)

    targets = _candidates(procs, ai_idle, mux_idle, kinds)
    if not targets:
        console.print(
            f"[green]clean[/] — nothing exceeds "
            f"ai_idle={human_duration(ai_idle)} / mux_idle={human_duration(mux_idle)}."
        )
        return 0

    table = Table(
        title=f"idle reap candidates ({len(targets)})",
        box=SIMPLE,
        caption="thresholds: ai=" + human_duration(ai_idle) + " mux=" + human_duration(mux_idle),
    )
    table.add_column("kind", style="bold yellow")
    table.add_column("pid", justify="right")
    table.add_column("rss", justify="right")
    table.add_column("cpu%", justify="right")
    table.add_column("idle", justify="right")
    table.add_column("cmd")
    total_rss = 0
    for p in targets:
        total_rss += p.rss
        table.add_row(
            p.kind,
            str(p.pid),
            human_bytes(p.rss),
            f"{p.cpu_percent:.1f}",
            human_duration(p.idle_seconds or 0),
            p.cmdline[:80],
        )
    console.print(table)
    console.print(f"[dim]would reclaim ~{human_bytes(total_rss)} RSS[/]\n")

    action = "DRY-RUN" if dry_run else ("SIGKILL" if force else "SIGTERM")
    if not confirm(f"{action} {len(targets)} idle session(s)?", default=False, assume_yes=assume_yes):
        console.print("[dim]cancelled[/]")
        return 0

    outcomes = terminate(targets, dry_run=dry_run, force=force)
    ok = sum(1 for o in outcomes if o.ok)
    fail = len(outcomes) - ok
    for o in outcomes:
        mark = "[green]✓[/]" if o.ok else "[red]✗[/]"
        console.print(f"{mark} pid={o.pid:<6} {o.kind:<8} {o.message}")
    console.print(f"\n[bold]done[/]: {ok} ok, {fail} failed")
    return 0 if fail == 0 else 1

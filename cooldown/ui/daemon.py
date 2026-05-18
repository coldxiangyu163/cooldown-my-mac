"""`cool daemon` — install / uninstall / status / logs / config-init / run."""
from __future__ import annotations

from pathlib import Path
from typing import Literal, cast

from rich.box import SIMPLE
from rich.console import Console
from rich.table import Table

from ..daemon import config as config_mod
from ..daemon import installer as installer_mod
from ..daemon import runner as runner_mod
from ..safety.confirm import confirm

Action = Literal["install", "uninstall", "status", "logs", "config-init", "run"]


def _print_outcome(console: Console, outcome: installer_mod.InstallOutcome) -> None:
    mark = "[green]✓[/]" if outcome.ok else "[red]✗[/]"
    console.print(f"{mark} plist: [bold]{outcome.plist_path}[/]")
    for msg in outcome.messages:
        console.print(f"  • {msg}")


def _tail(path: Path, n: int) -> list[str]:
    if not path.exists():
        return []
    try:
        with path.open("r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
    except OSError:
        return []
    return [line.rstrip("\n") for line in lines[-n:]]


def run(
    console: Console,
    *,
    action: Action,
    dry_run: bool = False,
    assume_yes: bool = False,
    force: bool = False,
    config_path: str | None = None,
) -> int:
    if action == "install":
        if not dry_run and not assume_yes and not confirm(
            "install cooldown launchd agent and start it now?",
            default=True,
            assume_yes=assume_yes,
        ):
            console.print("[dim]cancelled[/]")
            return 0
        outcome = installer_mod.install(dry_run=dry_run, force=force)
        _print_outcome(console, outcome)
        if outcome.ok and not dry_run:
            console.print(
                "[dim]tail logs:[/] "
                "[bold]tail -f ~/Library/Logs/cooldown/daemon.log[/]"
            )
        return 0 if outcome.ok else 1

    if action == "uninstall":
        if not dry_run and not assume_yes and not confirm(
            "remove cooldown launchd agent?",
            default=True,
            assume_yes=assume_yes,
        ):
            console.print("[dim]cancelled[/]")
            return 0
        outcome = installer_mod.uninstall(dry_run=dry_run)
        _print_outcome(console, outcome)
        return 0 if outcome.ok else 1

    if action == "status":
        st = installer_mod.status()
        table = Table(box=SIMPLE, show_header=False)
        table.add_column("key", style="bold")
        table.add_column("value")
        table.add_row("installed", "yes" if st["installed"] else "no")
        table.add_row("label", str(st["label"]))
        table.add_row("plist", str(st["plist_path"]))
        table.add_row("pid", str(st["pid"]) if st["pid"] is not None else "-")
        lx = st["last_exit_status"]
        table.add_row("last exit", str(lx) if lx is not None else "-")
        console.print(table)
        log_tail = cast("list[str]", st.get("log_tail") or [])
        if log_tail:
            console.print("[bold]recent log:[/]")
            for line in log_tail:
                console.print(f"  {line}")
        else:
            console.print("[dim]no log entries yet[/]")
        return 0

    if action == "logs":
        log_file = Path("~/Library/Logs/cooldown/daemon.log").expanduser()
        lines = _tail(log_file, 50)
        if not lines:
            console.print(f"[dim]no log at {log_file}[/]")
            return 0
        for line in lines:
            console.print(line)
        return 0

    if action == "config-init":
        target = Path(config_path).expanduser() if config_path else config_mod.default_path()
        try:
            written = config_mod.write_default(target, force=force)
        except FileExistsError:
            console.print(f"[yellow]config exists at {target} — pass --force to overwrite[/]")
            return 1
        console.print(f"[green]wrote default config[/] → {written}")
        return 0

    if action == "run":
        cfg = config_mod.load(config_path)
        console.print(
            f"[dim]cooldown daemon running (interval={cfg.interval_seconds}s, "
            f"dry_run={cfg.dry_run}) — ctrl-c to stop[/]"
        )
        return runner_mod.loop(cfg)

    console.print(f"[red]unknown action: {action}[/]")
    return 2

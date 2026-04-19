"""Typer CLI entry point: `cool` / `cooldown`."""
from __future__ import annotations

import sys

import typer
from rich.console import Console

from . import __version__
from .ui import dashboard, menu, pressure, procs, reap

app = typer.Typer(
    help="cooldown-my-mac · runtime thermal & workload manager",
    no_args_is_help=False,
    add_completion=False,
    pretty_exceptions_show_locals=False,
)
console = Console()


def _version_callback(value: bool) -> None:
    if value:
        console.print(f"cooldown {__version__}")
        raise typer.Exit()


@app.callback(invoke_without_command=True)
def _root(
    ctx: typer.Context,
    version: bool = typer.Option(
        False,
        "--version",
        "-V",
        help="Show version and exit.",
        callback=_version_callback,
        is_eager=True,
    ),
) -> None:
    if ctx.invoked_subcommand is not None:
        return
    # Interactive menu when called bare.
    choice = menu.run(console)
    if choice in (None, "quit"):
        raise typer.Exit()
    if choice == "status":
        dashboard.render(console)
    elif choice == "procs":
        procs.run(console)
    elif choice == "reap":
        reap.run(console)
    elif choice == "reap-dry":
        reap.run(console, dry_run=True)
    elif choice == "pressure":
        pressure.run(console)
    elif choice == "pressure-watch":
        pressure.run(console, mode="watch", notify=True)


@app.command(help="One-shot system health dashboard.")
def status() -> None:
    dashboard.render(console)


@app.command(name="procs", help="AI CLI inventory with interactive kill picker.")
def _procs_cmd(
    dry_run: bool = typer.Option(False, "--dry-run", help="Preview only, do not kill."),
    force: bool = typer.Option(False, "--force", "-9", help="Use SIGKILL instead of SIGTERM."),
    yes: bool = typer.Option(False, "--yes", "-y", help="Assume yes to confirmations."),
    kinds: list[str] = typer.Option(
        None,
        "--kind",
        "-k",
        help=(
            "Filter by kind (can repeat): droid, codex, claude, opencode, "
            "nanobot, hermes, tmux, cmux, zellij."
        ),
    ),
) -> None:
    code = procs.run(
        console,
        dry_run=dry_run,
        force=force,
        assume_yes=yes,
        kind_filter=kinds or None,
    )
    raise typer.Exit(code)


@app.command(name="reap", help="Reap idle AI CLI / multiplexer sessions.")
def _reap_cmd(
    ai_idle: int = typer.Option(
        reap.DEFAULT_AI_IDLE, "--ai-idle", help="Idle threshold (sec) for AI CLIs."
    ),
    mux_idle: int = typer.Option(
        reap.DEFAULT_MUX_IDLE, "--mux-idle", help="Idle threshold (sec) for tmux/cmux/zellij."
    ),
    dry_run: bool = typer.Option(False, "--dry-run", help="Preview only, do not kill."),
    force: bool = typer.Option(False, "--force", "-9", help="Use SIGKILL instead of SIGTERM."),
    yes: bool = typer.Option(False, "--yes", "-y", help="Assume yes to confirmations."),
    kinds: list[str] = typer.Option(
        None, "--kind", "-k", help="Limit reap to specific kinds."
    ),
) -> None:
    code = reap.run(
        console,
        ai_idle=ai_idle,
        mux_idle=mux_idle,
        dry_run=dry_run,
        force=force,
        assume_yes=yes,
        kinds=kinds or None,
    )
    raise typer.Exit(code)


@app.command(name="pressure", help="Memory pressure guard (one-shot or watch).")
def _pressure_cmd(
    watch: bool = typer.Option(False, "--watch", "-w", help="Loop forever at --interval seconds."),
    interval: int = typer.Option(60, "--interval", "-n", help="Seconds between samples in watch mode."),
    auto_reap: bool = typer.Option(False, "--auto-reap", help="Auto-run reap at CRITICAL."),
    auto_purge: bool = typer.Option(False, "--auto-purge", help="Auto-run `sudo purge` at CRITICAL."),
    notify: bool = typer.Option(False, "--notify", help="Send macOS notifications."),
    ai_idle: int = typer.Option(1800, "--ai-idle", help="Idle threshold (sec) for auto-reap."),
    ram_warn: float = typer.Option(0.80, "--ram-warn", help="RAM warn ratio (0..1)."),
    ram_crit: float = typer.Option(0.92, "--ram-crit", help="RAM critical ratio (0..1)."),
    swap_warn: float = typer.Option(0.40, "--swap-warn", help="Swap warn ratio (0..1)."),
    swap_crit: float = typer.Option(0.80, "--swap-crit", help="Swap critical ratio (0..1)."),
    comp_warn: float = typer.Option(0.15, "--comp-warn", help="Compressor warn ratio (0..1)."),
    comp_crit: float = typer.Option(0.25, "--comp-crit", help="Compressor critical ratio (0..1)."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Preview auto-reap/purge, don't run."),
    yes: bool = typer.Option(False, "--yes", "-y", help="Assume yes to confirmations."),
) -> None:
    code = pressure.run(
        console,
        mode="watch" if watch else "once",
        interval=interval,
        auto_reap=auto_reap,
        auto_purge=auto_purge,
        notify=notify,
        ai_idle=ai_idle,
        ram_warn=ram_warn,
        ram_crit=ram_crit,
        swap_warn=swap_warn,
        swap_crit=swap_crit,
        comp_warn=comp_warn,
        comp_crit=comp_crit,
        dry_run=dry_run,
        assume_yes=yes,
    )
    raise typer.Exit(code)


def main() -> None:
    try:
        app()
    except KeyboardInterrupt:
        console.print("[dim]interrupted[/]")
        sys.exit(130)


if __name__ == "__main__":
    main()

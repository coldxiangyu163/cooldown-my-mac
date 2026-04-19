"""Typer CLI entry point: `cool` / `cooldown`."""
from __future__ import annotations

import sys

import typer
from rich.console import Console

from . import __version__
from .ui import (
    apps as apps_ui,
)
from .ui import (
    daemon as daemon_ui,
)
from .ui import (
    dashboard,
    menu,
    pressure,
    procs,
    reap,
)
from .ui import (
    launchd as launchd_ui,
)
from .ui import (
    services as services_ui,
)
from .ui import (
    thermal as thermal_ui,
)
from .ui import (
    watch as watch_ui,
)

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
    elif choice == "services":
        services_ui.run(console)
    elif choice == "apps-list":
        apps_ui.run(console, action="list")
    elif choice == "apps-suspend":
        apps_ui.run(console, action="suspend")
    elif choice == "apps-resume":
        apps_ui.run(console, action="resume")
    elif choice == "thermal":
        thermal_ui.run(console)
    elif choice == "launchd":
        launchd_ui.run(console)
    elif choice == "launchd-audit":
        launchd_ui.run(console, audit=True, disable=True)
    elif choice == "daemon-status":
        daemon_ui.run(console, action="status")
    elif choice == "watch":
        watch_ui.run(console)


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


@app.command(name="services", help="Start / stop local dev services (mysql/postgres/redis/...).")
def _services_cmd(
    dry_run: bool = typer.Option(False, "--dry-run", help="Preview only."),
    yes: bool = typer.Option(False, "--yes", "-y", help="Assume yes to confirmations."),
    only: list[str] = typer.Option(None, "--only", "-o", help="Filter by kind (mysql, postgres, redis, ...)."),
) -> None:
    code = services_ui.run(console, dry_run=dry_run, assume_yes=yes, only=only or None)
    raise typer.Exit(code)


apps_app = typer.Typer(help="List / suspend / resume / quit heavy background apps.")
app.add_typer(apps_app, name="apps")


@apps_app.command("list", help="List heavy background apps.")
def _apps_list() -> None:
    raise typer.Exit(apps_ui.run(console, action="list"))


@apps_app.command("suspend", help="SIGSTOP a process tree (freezes CPU until resumed).")
def _apps_suspend(
    yes: bool = typer.Option(False, "--yes", "-y"),
    dry_run: bool = typer.Option(False, "--dry-run"),
    kinds: list[str] = typer.Option(None, "--kind", "-k"),
) -> None:
    raise typer.Exit(
        apps_ui.run(console, action="suspend", dry_run=dry_run, assume_yes=yes, kinds=kinds or None)
    )


@apps_app.command("resume", help="SIGCONT a previously suspended app.")
def _apps_resume(
    yes: bool = typer.Option(False, "--yes", "-y"),
    dry_run: bool = typer.Option(False, "--dry-run"),
    kinds: list[str] = typer.Option(None, "--kind", "-k"),
) -> None:
    raise typer.Exit(
        apps_ui.run(console, action="resume", dry_run=dry_run, assume_yes=yes, kinds=kinds or None)
    )


@apps_app.command("quit", help="Gracefully quit (osascript) then SIGTERM.")
def _apps_quit(
    yes: bool = typer.Option(False, "--yes", "-y"),
    dry_run: bool = typer.Option(False, "--dry-run"),
    kinds: list[str] = typer.Option(None, "--kind", "-k"),
) -> None:
    raise typer.Exit(
        apps_ui.run(console, action="quit", dry_run=dry_run, assume_yes=yes, kinds=kinds or None)
    )


@app.command(name="thermal", help="Thermal dashboard (pmset + SMC) + optional sleep-policy restore.")
def _thermal_cmd(
    restore: bool = typer.Option(False, "--restore", help="Restore safe sleep defaults (displaysleep/disksleep=10)."),
    dry_run: bool = typer.Option(False, "--dry-run"),
    yes: bool = typer.Option(False, "--yes", "-y"),
) -> None:
    raise typer.Exit(
        thermal_ui.run(console, restore=restore, dry_run=dry_run, assume_yes=yes)
    )


@app.command(name="launchd", help="Audit launchd agents/daemons; optionally disable noisy ones.")
def _launchd_cmd(
    audit: bool = typer.Option(False, "--audit", help="Show full non-Apple table."),
    disable_: bool = typer.Option(False, "--disable", help="Enable interactive disable picker."),
    category: str = typer.Option(None, "--category", "-c", help="Filter: apple|homebrew|third-party|user|unknown"),
    dry_run: bool = typer.Option(False, "--dry-run"),
    yes: bool = typer.Option(False, "--yes", "-y"),
) -> None:
    raise typer.Exit(
        launchd_ui.run(
            console,
            audit=audit,
            disable=disable_,
            category=category,
            dry_run=dry_run,
            assume_yes=yes,
        )
    )


daemon_app = typer.Typer(help="Background launchd agent (rule engine).")
app.add_typer(daemon_app, name="daemon")


@daemon_app.command("install", help="Install launchd plist and start the agent.")
def _daemon_install(
    dry_run: bool = typer.Option(False, "--dry-run"),
    yes: bool = typer.Option(False, "--yes", "-y"),
) -> None:
    raise typer.Exit(daemon_ui.run(console, action="install", dry_run=dry_run, assume_yes=yes))


@daemon_app.command("uninstall", help="Stop and remove the launchd agent.")
def _daemon_uninstall(
    dry_run: bool = typer.Option(False, "--dry-run"),
    yes: bool = typer.Option(False, "--yes", "-y"),
) -> None:
    raise typer.Exit(daemon_ui.run(console, action="uninstall", dry_run=dry_run, assume_yes=yes))


@daemon_app.command("status", help="Show daemon PID + recent log tail.")
def _daemon_status() -> None:
    raise typer.Exit(daemon_ui.run(console, action="status"))


@daemon_app.command("logs", help="Tail the daemon log.")
def _daemon_logs() -> None:
    raise typer.Exit(daemon_ui.run(console, action="logs"))


@daemon_app.command("config-init", help="Write ~/.config/cooldown/daemon.yaml with commented defaults.")
def _daemon_config_init(
    force: bool = typer.Option(False, "--force", help="Overwrite existing config."),
) -> None:
    raise typer.Exit(daemon_ui.run(console, action="config-init", force=force))


@daemon_app.command("run", help="Run the rule engine in the foreground (used by launchd).")
def _daemon_run(
    config: str = typer.Option(None, "--config", "-c", help="Alternate YAML path."),
) -> None:
    raise typer.Exit(daemon_ui.run(console, action="run", config_path=config))


@app.command(name="watch", help="Full-screen Textual live dashboard (requires `textual`).")
def _watch_cmd(
    interval: int = typer.Option(3, "--interval", "-n", help="Refresh interval seconds."),
) -> None:
    raise typer.Exit(watch_ui.run(console, interval=interval))


def main() -> None:
    try:
        app()
    except KeyboardInterrupt:
        console.print("[dim]interrupted[/]")
        sys.exit(130)


if __name__ == "__main__":
    main()

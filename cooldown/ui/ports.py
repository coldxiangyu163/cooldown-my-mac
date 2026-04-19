"""`cool ports` — listening-port map with optional kill.

Gives the user a quick answer to "what's listening on port X / in this
range / causing this conflict, and which project is holding it?". Kill
flow reuses :func:`cooldown.actions.reap.terminate` so self-protection
and the op-log trail behave identically to the ``cool reap`` command.
"""
from __future__ import annotations

import questionary
from rich.box import SIMPLE
from rich.console import Console
from rich.table import Table

from ..actions.reap import terminate
from ..collectors import ports as ports_mod
from ..collectors.procs import ProcInfo
from ..safety.confirm import confirm

# Parallel-worker contract: ancestry / project collectors may not yet
# exist. When they're missing we still render a useful table with "-" in
# the launcher / project columns.
try:
    from ..collectors import ancestry as _ancestry_mod
except ImportError:
    _ancestry_mod = None  # type: ignore[assignment]
try:
    from ..collectors import project as _project_mod
except ImportError:
    _project_mod = None  # type: ignore[assignment]


# Apple / system daemons that are almost never the thing the user is
# actually looking for. Hidden unless --all is passed.
_APPLE_NOISE: frozenset[str] = frozenset(
    {
        "rapportd",
        "sharingd",
        "ControlCe",
        "identityservicesd",
        "remoted",
        "mDNSResponder",
        "rpc.yppasswdd",
        "rpcbind",
        "netbiosd",
        "cfprefsd",
    }
)


def _is_apple_noise(process: str) -> bool:
    if not process:
        return False
    if process in _APPLE_NOISE:
        return True
    return process.startswith("com.apple.")


def _parse_port_arg(value: str) -> list[int]:
    out: list[int] = []
    for part in value.split(","):
        part = part.strip()
        if not part:
            continue
        try:
            out.append(int(part))
        except ValueError:
            continue
    return out


def _parse_range_arg(value: str) -> tuple[int, int] | None:
    if ":" not in value:
        return None
    a, _, b = value.partition(":")
    try:
        return int(a), int(b)
    except ValueError:
        return None


def _launcher_for(pid: int) -> str:
    if _ancestry_mod is None:
        return "-"
    try:
        res = _ancestry_mod.find_launcher(pid)
    except Exception:  # noqa: BLE001
        return "-"
    if res is None:
        return "-"
    # Tolerate Launcher objects (A1's API exposes .label and .kind) and raw strings.
    for attr in ("label", "name", "kind"):
        val = getattr(res, attr, None)
        if val:
            return str(val)
    return str(res)


def _project_for(pid: int) -> tuple[str, str]:
    """Return (project_name, project_path) or ("-", "") on lookup failure."""
    if _project_mod is None:
        return "-", ""
    try:
        res = _project_mod.lookup(pid)
    except Exception:  # noqa: BLE001
        return "-", ""
    if res is None:
        return "-", ""
    name = getattr(res, "name", None) or getattr(res, "project", None) or str(res)
    path = getattr(res, "path", "") or getattr(res, "root", "")
    return str(name), str(path)


def _truncate(s: str, width: int) -> str:
    if len(s) <= width:
        return s
    return s[: max(0, width - 1)] + "…"


def _print_table(
    console: Console,
    entries: list[ports_mod.PortEntry],
    launchers: dict[int, str],
    projects: dict[int, tuple[str, str]],
    title: str,
) -> None:
    if not entries:
        console.print("[dim]no listening ports matched the filter.[/]")
        return
    table = Table(title=title, box=SIMPLE, show_lines=False)
    table.add_column("port", justify="right", style="bold yellow")
    table.add_column("proto/bind", style="cyan")
    table.add_column("pid", justify="right", style="cyan")
    table.add_column("process")
    table.add_column("project")
    table.add_column("launcher", style="dim")
    table.add_column("command")

    for e in entries:
        hint = ports_mod.by_project_hint(e.port)
        proj_name, _ = projects.get(e.pid, ("-", ""))
        proj_label = f"[dim]{hint}[/]" if (proj_name == "-" and hint) else proj_name
        table.add_row(
            str(e.port),
            f"{e.proto}/{e.bind}",
            str(e.pid),
            e.process or "-",
            proj_label,
            launchers.get(e.pid, "-"),
            _truncate(e.command, 60),
        )
    console.print(table)


def _label(e: ports_mod.PortEntry, project: str) -> str:
    cmd = _truncate(e.command, 50)
    return (
        f"port={e.port:<6} {e.proto:<5}/{e.bind:<15} "
        f"pid={e.pid:<6} {e.process:<12} proj={project:<12} {cmd}"
    )


def _to_procinfo(e: ports_mod.PortEntry) -> ProcInfo:
    return ProcInfo(
        pid=e.pid,
        ppid=0,
        kind="port",
        name=e.process,
        cmdline=e.command,
        rss=0,
        cpu_percent=0.0,
        create_time=0.0,
        age=0.0,
        tty=None,
        user=e.user,
        idle_seconds=None,
    )


def _collect_and_filter(
    *,
    port: str | None,
    range_: str | None,
    project_filter: str | None,
    conflict: bool,
    show_all: bool,
) -> tuple[list[ports_mod.PortEntry], dict[int, str], dict[int, tuple[str, str]]]:
    entries = ports_mod.collect()
    ports_mod.enrich_command(entries)

    # Port / range filtering.
    if port:
        wanted = set(_parse_port_arg(port))
        if wanted:
            entries = [e for e in entries if e.port in wanted]
    if range_:
        parsed = _parse_range_arg(range_)
        if parsed is not None:
            entries = ports_mod.range_filter(entries, parsed[0], parsed[1])

    # Hide Apple noise unless asked.
    if not show_all:
        entries = [e for e in entries if not _is_apple_noise(e.process)]

    # Resolve optional metadata once per pid.
    unique_pids = {e.pid for e in entries}
    launchers = {pid: _launcher_for(pid) for pid in unique_pids}
    projects = {pid: _project_for(pid) for pid in unique_pids}

    # Project-name filtering.
    if project_filter:
        needle = project_filter.lower()
        keep_pids = {
            pid
            for pid, (name, _path) in projects.items()
            if name != "-" and needle in name.lower()
        }
        entries = [e for e in entries if e.pid in keep_pids]

    # Conflict filter is applied last so it composes with the others.
    if conflict:
        conflict_ports = {p for p, _ in ports_mod.find_conflicts(entries)}
        entries = [e for e in entries if e.port in conflict_ports]

    entries.sort(key=lambda e: (e.port, e.pid, e.bind))
    return entries, launchers, projects


def _print_free(
    console: Console,
    entries: list[ports_mod.PortEntry],
    free_spec: str,
) -> int:
    parsed = _parse_range_arg(free_spec)
    if parsed is None:
        console.print(f"[red]invalid --free range:[/] {free_spec}")
        return 2
    lo, hi = (parsed[0], parsed[1]) if parsed[0] <= parsed[1] else (parsed[1], parsed[0])
    taken = {e.port for e in entries}
    free_ports = [p for p in range(lo, hi + 1) if p not in taken]
    if not free_ports:
        console.print(f"[dim]no free ports in range {lo}-{hi}.[/]")
        return 0
    console.print(f"[bold]free ports in {lo}-{hi}:[/] {len(free_ports)}")
    # Group contiguous runs for readability.
    runs: list[tuple[int, int]] = []
    start = prev = free_ports[0]
    for p in free_ports[1:]:
        if p == prev + 1:
            prev = p
            continue
        runs.append((start, prev))
        start = prev = p
    runs.append((start, prev))
    rendered = ", ".join(f"{a}" if a == b else f"{a}-{b}" for a, b in runs)
    console.print(rendered)
    return 0


def run(
    console: Console,
    *,
    port: str | None = None,
    range_: str | None = None,
    project_filter: str | None = None,
    conflict: bool = False,
    free: str | None = None,
    kill: bool = False,
    dry_run: bool = False,
    force: bool = False,
    assume_yes: bool = False,
    show_all: bool = False,
) -> int:
    with console.status("[dim]scanning listening ports...[/]", spinner="dots"):
        # --free works off the raw collection; skip the Apple-noise filter
        # since we're answering "is this port taken by *anything*".
        if free:
            raw = ports_mod.collect()
            return _print_free(console, raw, free)

        entries, launchers, projects = _collect_and_filter(
            port=port,
            range_=range_,
            project_filter=project_filter,
            conflict=conflict,
            show_all=show_all,
        )

    title = "listening ports"
    if conflict:
        title = "listening ports — conflicts"
    elif port:
        title = f"listening ports — {port}"
    elif range_:
        title = f"listening ports — {range_}"

    _print_table(console, entries, launchers, projects, title)

    if not kill or not entries:
        return 0

    # Deduplicate by pid so we don't ask psutil to signal the same process
    # twice (a single `node` serving ipv4+ipv6 would otherwise appear twice).
    seen: set[int] = set()
    pickable: list[ports_mod.PortEntry] = []
    for e in entries:
        if e.pid in seen:
            continue
        seen.add(e.pid)
        pickable.append(e)

    try:
        picks = questionary.checkbox(
            "Select port owners to terminate (space = toggle, enter = confirm):",
            choices=[
                questionary.Choice(
                    title=_label(e, projects.get(e.pid, ("-", ""))[0]),
                    value=e,
                    checked=False,
                )
                for e in pickable
            ],
        ).ask()
    except KeyboardInterrupt:
        console.print("[dim]cancelled[/]")
        return 0
    if not picks:
        console.print("[dim]nothing selected.[/]")
        return 0

    action = "DRY-RUN terminate" if dry_run else ("SIGKILL" if force else "SIGTERM")
    if not confirm(
        f"{action} {len(picks)} process(es) holding listening ports?",
        default=False,
        assume_yes=assume_yes,
    ):
        console.print("[dim]cancelled[/]")
        return 0

    outcomes = terminate([_to_procinfo(e) for e in picks], dry_run=dry_run, force=force)
    ok = sum(1 for o in outcomes if o.ok)
    fail = len(outcomes) - ok
    for o in outcomes:
        mark = "[green]✓[/]" if o.ok else "[red]✗[/]"
        console.print(f"{mark} pid={o.pid:<6} {o.message}")
    console.print(f"\n[bold]done[/]: {ok} ok, {fail} failed")
    return 0 if fail == 0 else 1

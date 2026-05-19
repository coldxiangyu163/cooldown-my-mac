"""Listening-port collector.

Shells out to ``lsof`` **once** and parses the ``-F`` machine format into
a flat list of :class:`PortEntry` records so UI code can answer the
question "which process (and which project) is holding this port".

Using ``-F pcnPLT`` yields, per listening socket, the pid (``p``),
command name (``c``), login name (``L``), protocol (``P``), address /
port (``n``) and TCP state (``T``). Records for additional sockets owned
by the same process re-use the already seen ``p/c/L`` headers, so we
emit one :class:`PortEntry` per *file* (``f``) block rather than per
process.
"""
from __future__ import annotations

import subprocess
from dataclasses import dataclass

import psutil

from ..util import PROC_ERRORS

_WELL_KNOWN: dict[int, str] = {
    22: "ssh",
    80: "http",
    443: "https",
    3306: "mysql",
    5432: "postgres",
    5900: "vnc",
    6379: "redis",
    9200: "elastic",
    9222: "chrome-devtools",
    27017: "mongo",
}


@dataclass
class PortEntry:
    port: int
    proto: str  # tcp4 | tcp6 | tcp46
    bind: str  # "127.0.0.1", "*", "::1", etc.
    pid: int
    process: str
    user: str
    command: str = ""


def _run_lsof() -> str:
    """Invoke lsof once. Swallow every failure mode into empty output."""
    try:
        r = subprocess.run(
            ["lsof", "-iTCP", "-sTCP:LISTEN", "-P", "-n", "-F", "pcnPLT"],
            check=False,
            capture_output=True,
            text=True,
            timeout=5.0,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    return r.stdout or ""


def _split_bind_port(raw: str) -> tuple[str, int] | None:
    """Parse an lsof ``n`` field into ``(bind, port)``.

    Handles IPv4 (``127.0.0.1:5432``), IPv6 with brackets
    (``[::1]:5432``), and wildcard (``*:5432``). Returns ``None`` when
    the address cannot be parsed or the port is not numeric.
    """
    if not raw:
        return None
    # Strip any trailing "->" peer info just in case; listeners shouldn't
    # have a peer but be defensive.
    if "->" in raw:
        raw = raw.split("->", 1)[0]

    if raw.startswith("["):
        # [::1]:5432
        end = raw.find("]")
        if end == -1:
            return None
        host = raw[1:end]
        rest = raw[end + 1 :]
        if not rest.startswith(":"):
            return None
        port_s = rest[1:]
    else:
        # IPv4 or wildcard
        if ":" not in raw:
            return None
        host, _, port_s = raw.rpartition(":")
    try:
        port = int(port_s)
    except ValueError:
        return None
    return host, port


def _parse_lsof(output: str) -> list[PortEntry]:
    entries: list[PortEntry] = []
    pid: int | None = None
    command = ""
    user = ""
    # Per-file state.
    proto = ""
    name = ""

    def flush() -> None:
        if pid is None or not name:
            return
        parsed = _split_bind_port(name)
        if parsed is None:
            return
        bind, port = parsed
        # Determine proto family from the bind address: bracket-wrapped or
        # containing colons (uncompressed IPv6) ⇒ tcp6; "*" is ambiguous
        # and treated as tcp4 (lsof emits two rows for dual-stack sockets,
        # one per family, when applicable).
        is_v6 = name.startswith("[") or (bind != "*" and ":" in bind)
        if proto.lower() == "tcp":
            family = "tcp6" if is_v6 else "tcp4"
        else:
            family = proto.lower() or ("tcp6" if is_v6 else "tcp4")
        entries.append(
            PortEntry(
                port=port,
                proto=family,
                bind=bind,
                pid=pid,
                process=command,
                user=user,
            )
        )

    has_file = False
    for raw_line in output.splitlines():
        if not raw_line:
            continue
        key = raw_line[0]
        val = raw_line[1:]
        if key == "p":
            # Flush the previous socket (if any) before entering a new
            # process block.
            if has_file:
                flush()
                has_file = False
                proto = ""
                name = ""
            try:
                pid = int(val)
            except ValueError:
                pid = None
            command = ""
            user = ""
        elif key == "c":
            command = val
        elif key == "L":
            user = val
        elif key == "f":
            # Boundary between files; flush previous then reset.
            if has_file:
                flush()
            has_file = True
            proto = ""
            name = ""
        elif key == "P":
            proto = val
        elif key == "n":
            name = val
        # T, other keys: ignored (we asked for LISTEN sockets only).

    if has_file:
        flush()

    return entries


def collect() -> list[PortEntry]:
    """Return every LISTEN-state TCP socket currently visible to lsof."""
    return _parse_lsof(_run_lsof())


def range_filter(entries: list[PortEntry], start: int, end: int) -> list[PortEntry]:
    """Return only entries whose port is within ``[start, end]`` inclusive."""
    lo, hi = (start, end) if start <= end else (end, start)
    return [e for e in entries if lo <= e.port <= hi]


def find_conflicts(entries: list[PortEntry]) -> list[tuple[int, list[PortEntry]]]:
    """Group entries by port and return groups where >1 *distinct* pid binds it.

    Same-pid IPv4+IPv6 dual-listeners are not a conflict.
    """
    by_port: dict[int, list[PortEntry]] = {}
    for e in entries:
        by_port.setdefault(e.port, []).append(e)
    out: list[tuple[int, list[PortEntry]]] = []
    for port, items in by_port.items():
        pids = {i.pid for i in items}
        if len(pids) > 1:
            out.append((port, items))
    out.sort(key=lambda x: x[0])
    return out


def collapse_inherited(
    entries: list[PortEntry],
    ancestors: dict[int, set[int]],
) -> tuple[list[PortEntry], dict[int, list[int]]]:
    """Collapse parent/child reloader rows that share one listening socket.

    When a process forks (uvicorn ``--reload``, flask reloader, …) the
    child inherits the parent's listening fd, so ``lsof -sTCP:LISTEN``
    reports both — yet there is only one listener in the kernel. This
    folds children into their root and returns the inheriting PIDs as
    "workers" so callers can still surface them.

    ``ancestors[pid]`` is the set of pids in ``pid``'s ancestor chain.
    A PID with no in-group ancestor is treated as a root; a PID with
    one or more is treated as a child of the deepest in-group ancestor.

    PIDs unrelated to each other on the same port (the real "conflict"
    case — two daemons fighting for the same socket) stay as separate
    roots so callers can still flag them.
    """
    by_port: dict[int, list[PortEntry]] = {}
    for e in entries:
        by_port.setdefault(e.port, []).append(e)

    kept: list[PortEntry] = []
    workers: dict[int, list[int]] = {}
    for items in by_port.values():
        pids_on_port = {e.pid for e in items}
        if len(pids_on_port) <= 1:
            kept.extend(items)
            continue
        roots: set[int] = set()
        children: set[int] = set()
        for pid in pids_on_port:
            if ancestors.get(pid, set()) & (pids_on_port - {pid}):
                children.add(pid)
            else:
                roots.add(pid)
        if not children:
            kept.extend(items)
            continue
        # Map each child to its nearest in-group ancestor (the root it
        # inherited the socket from). Falls back to "any root" if the
        # chain isn't fully observable.
        for child in children:
            anc_in_group = ancestors.get(child, set()) & roots
            if anc_in_group:
                root_pid = next(iter(anc_in_group))
                workers.setdefault(root_pid, []).append(child)
        kept.extend(e for e in items if e.pid in roots)
    return kept, workers


def enrich_command(entries: list[PortEntry]) -> None:
    """Populate ``entry.command`` with the process cmdline. One psutil
    lookup per unique pid. Failures leave ``command`` as the empty string.
    """
    seen: dict[int, str] = {}
    for e in entries:
        if e.pid in seen:
            e.command = seen[e.pid]
            continue
        try:
            p = psutil.Process(e.pid)
            try:
                cmd = " ".join(p.cmdline())
            except PROC_ERRORS:
                cmd = ""
        except PROC_ERRORS:
            cmd = ""
        seen[e.pid] = cmd
        e.command = cmd


def by_project_hint(port: int) -> str | None:
    """Return a short human label for well-known ports, else ``None``.

    This is *not* a project mapping — it's a protocol/service hint used
    to give users orientation when the actual project can't be resolved.
    """
    return _WELL_KNOWN.get(port)

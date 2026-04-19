"""Local dev service inventory: brew services + psutil cross-reference."""
from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass

import psutil

# Classification table: kind -> (brew_names, process name needles)
# brew_names: possible names under `brew services list` (first is the
# preferred canonical one we'll pass to `brew services start/stop`).
# The process needles are matched case-insensitively against both the
# process name and the full command line.
SERVICE_TABLE: list[tuple[str, tuple[str, ...], tuple[str, ...]]] = [
    ("mysql", ("mysql", "mysql@8.0", "mysql@5.7", "mariadb"), ("mysqld",)),
    (
        "postgres",
        ("postgresql", "postgresql@16", "postgresql@15", "postgresql@14", "postgresql@13"),
        ("postgres", "postmaster"),
    ),
    ("redis", ("redis",), ("redis-server",)),
    ("mongo", ("mongodb-community", "mongodb"), ("mongod",)),
    (
        "elastic",
        ("elasticsearch", "elasticsearch-full"),
        ("elasticsearch", "org.elasticsearch.bootstrap"),
    ),
    ("nanobot", ("nanobot",), ("nanobot",)),
    ("hermes", ("hermes",), ("hermes",)),
    ("mosquitto", ("mosquitto",), ("mosquitto",)),
]


@dataclass
class ServiceInfo:
    name: str
    kind: str
    pid: int | None
    rss: int
    cpu_percent: float
    running: bool
    brew_managed: bool
    brew_status: str | None


def _brew_available() -> bool:
    return shutil.which("brew") is not None


def _brew_services_list() -> list[dict]:
    """Return parsed `brew services list --json`, or [] if unavailable."""
    if not _brew_available():
        return []
    try:
        proc = subprocess.run(
            ["brew", "services", "list", "--json"],
            capture_output=True,
            text=True,
            timeout=8,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return []
    if proc.returncode != 0 or not proc.stdout.strip():
        return []
    try:
        data = json.loads(proc.stdout)
    except json.JSONDecodeError:
        return []
    if not isinstance(data, list):
        return []
    return data


def _classify_brew(name: str) -> str | None:
    lname = name.lower()
    for kind, brew_names, _ in SERVICE_TABLE:
        if lname in {b.lower() for b in brew_names}:
            return kind
    return None


def _classify_proc(name: str, cmdline: str) -> str | None:
    hay = f"{name} {cmdline}".lower()
    for kind, _, needles in SERVICE_TABLE:
        for needle in needles:
            if needle in hay:
                return kind
    return None


def _sample_proc(p: psutil.Process) -> tuple[int, float]:
    """Return (rss, cpu_percent) sampled over a tiny interval."""
    try:
        with p.oneshot():
            p.cpu_percent(None)
            rss = p.memory_info().rss
        cpu = p.cpu_percent(0.15)
        ncpu = psutil.cpu_count(logical=True) or 1
        return rss, cpu / ncpu
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        return 0, 0.0


def _scan_processes() -> dict[str, list[psutil.Process]]:
    """Group live processes by our service kind."""
    groups: dict[str, list[psutil.Process]] = {}
    for p in psutil.process_iter(["pid", "name", "cmdline"]):
        try:
            name = p.info["name"] or ""
            cmd = " ".join(p.info["cmdline"] or [])
            kind = _classify_proc(name, cmd)
            if kind is None:
                continue
            groups.setdefault(kind, []).append(p)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return groups


def collect() -> list[ServiceInfo]:
    """Return current local dev services we know about.

    Strategy:
      1. Enumerate `brew services list --json` (if brew exists).
      2. Enumerate live processes matching our known needles.
      3. Produce one ServiceInfo per distinct (kind, name) — so a service
         may appear with `running=False` if brew knows it but it's stopped,
         and an unmanaged service may appear with `brew_managed=False`.
    """
    out: list[ServiceInfo] = []
    seen: set[tuple[str, str]] = set()

    brew_entries = _brew_services_list()
    proc_groups = _scan_processes()

    for entry in brew_entries:
        name = str(entry.get("name") or "").strip()
        if not name:
            continue
        kind = _classify_brew(name)
        if kind is None:
            continue
        status = str(entry.get("status") or "unknown")
        pid_field = entry.get("pid")
        pid: int | None
        try:
            pid = int(pid_field) if pid_field not in (None, "", 0) else None
        except (TypeError, ValueError):
            pid = None

        rss = 0
        cpu = 0.0
        running = status.lower() == "started" or pid is not None
        if pid is not None:
            try:
                rss, cpu = _sample_proc(psutil.Process(pid))
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pid = None
                running = status.lower() == "started"

        # If brew didn't give a pid but a matching live proc exists, adopt it.
        if pid is None and kind in proc_groups and proc_groups[kind]:
            candidate = min(proc_groups[kind], key=lambda pr: pr.pid)
            pid = candidate.pid
            rss, cpu = _sample_proc(candidate)
            running = True

        out.append(
            ServiceInfo(
                name=name,
                kind=kind,
                pid=pid,
                rss=rss,
                cpu_percent=cpu,
                running=running,
                brew_managed=True,
                brew_status=status,
            )
        )
        seen.add((kind, name))

    # Second pass: live processes with no brew entry at all.
    for kind, procs in proc_groups.items():
        if any(k == kind for k, _ in seen):
            continue
        # Pick the smallest-pid as the representative process for the kind.
        rep = min(procs, key=lambda pr: pr.pid)
        try:
            display_name = rep.name() or kind
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            display_name = kind
        rss, cpu = _sample_proc(rep)
        out.append(
            ServiceInfo(
                name=display_name,
                kind=kind,
                pid=rep.pid,
                rss=rss,
                cpu_percent=cpu,
                running=True,
                brew_managed=False,
                brew_status=None,
            )
        )
        seen.add((kind, display_name))

    out.sort(key=lambda s: (not s.running, s.kind, s.name))
    return out

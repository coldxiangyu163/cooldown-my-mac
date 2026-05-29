"""TOP processes ranked by current CPU usage, grouped by owning application.

Why this lives alongside ``procs.py`` instead of merging in:
``procs.collect()`` deliberately filters to AI / multiplexer kinds, so a
runaway Python script spawned by hermes-cron or a misbehaving Chrome
renderer never surfaces. ``cool status`` / ``cool watch`` needed a panel
that answers "which app is burning cores *right now*", which is a strictly
different question from "which AI CLI families are loaded". Keeping them
split avoids cross-cutting changes to ``ProcInfo`` and ``group_by_kind``.

Two units live here, on purpose:

* ``HotProc.cpu_percent`` is normalized to a "share of total CPU capacity"
  (``raw / ncpu``) so a single value plugs into the AI CLI Inventory
  column. On an N-core box a process pinning one full core reads as
  ``100/N`` — tiny, and misleading on its own.
* ``HotApp.cores`` re-expresses the same work as "how many cores is this
  app eating" (``Σ raw / 100``). That is the number a human reads as
  "Chrome is using 13 cores", so it is what the panels lead with.
"""
from __future__ import annotations

import re
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

import psutil

from ..util import PROC_ERRORS

if TYPE_CHECKING:  # avoid runtime import cycle (leftovers imports HotApp)
    from .leftovers import BrowserOrigin


@dataclass
class HotProc:
    pid: int
    name: str
    cmdline: str
    cpu_percent: float  # normalized to total-CPU share (matches procs.ProcInfo)
    rss: int
    user: str
    create_time: float
    age: float
    # Executable path, used to attribute the process to a ``.app`` bundle.
    # Defaults to "" so older call sites / tests that build HotProc without
    # it keep working.
    exe: str = ""


@dataclass
class HotApp:
    """One application's worth of hot processes, aggregated."""

    app: str
    cores: float  # Σ(raw cpu) / 100 — "how many cores is this app eating"
    pct_sys: float  # Σ(normalized cpu_percent) — share of total CPU capacity
    nproc: int
    rss: int
    pids: list[int]
    procs: list[HotProc]  # members, CPU-descending, for drill-down
    # Set by ``leftovers.annotate_origins`` when this group looks like an
    # orphaned automation browser. None for ordinary apps.
    origin: BrowserOrigin | None = None


@dataclass
class Coverage:
    """How much of the attributable CPU the shown groups actually cover.

    Lets the panel say "shown 73% · +52 procs 12%" so the user can tell the
    view is honest instead of silently hiding half the load below rank N.
    """

    total_pct_sys: float  # Σ over ALL non-zero procs
    shown_pct_sys: float  # Σ over the groups actually displayed
    tail_pct_sys: float  # the remainder hidden below the cut
    tail_nproc: int  # how many processes live in that tail


# Matches the *leftmost* ``/<Bundle>.app/`` in a path. Leftmost wins so a
# nested helper bundle (``Visual Studio Code.app/.../Code Helper.app``)
# attributes to the outer app. ``[^/]+?`` (non-greedy, any non-slash) keeps
# bundle names with spaces — "Google Chrome", "Visual Studio Code".
_APP_RE = re.compile(r"/([^/]+?)\.app(?:/|$)")


def group_key(exe: str, cmdline: str, name: str) -> str:
    """Return the display group an individual process belongs to.

    ``.app`` bundle name when the binary lives inside one (collapses
    Chrome's whole helper fleet into "Google Chrome"); otherwise the bare
    process name (so a stray ``python3.13`` still groups by something
    meaningful). Never returns empty.
    """
    for hay in (exe, cmdline):
        if hay:
            m = _APP_RE.search(hay)
            if m:
                return m.group(1)
    return name or "?"


def aggregate_by_app(
    procs: list[HotProc],
    ncpu: int,
    top_n: int = 8,
    key_fn: Callable[[str, str, str], str] = group_key,
) -> tuple[list[HotApp], Coverage]:
    """Group hot processes by owning app and return the top ``top_n`` plus a
    coverage summary describing the hidden tail.

    ``key_fn(exe, cmdline, name) -> group`` defaults to the generic
    ``group_key``; callers can inject a smarter key (e.g. one that splits an
    automation browser out from the user's real browser) without coupling
    this module to that logic.
    """
    ncpu = max(1, ncpu)
    groups: dict[str, list[HotProc]] = {}
    for p in procs:
        groups.setdefault(key_fn(p.exe, p.cmdline, p.name), []).append(p)

    apps: list[HotApp] = []
    for app, members in groups.items():
        members.sort(key=lambda m: (-m.cpu_percent, m.pid))
        pct_sys = sum(m.cpu_percent for m in members)
        apps.append(
            HotApp(
                app=app,
                cores=pct_sys * ncpu / 100.0,
                pct_sys=pct_sys,
                nproc=len(members),
                rss=sum(m.rss for m in members),
                pids=[m.pid for m in members],
                procs=members,
            )
        )
    apps.sort(key=lambda a: (-a.cores, a.app))

    shown = apps[:top_n]
    total_pct = sum(a.pct_sys for a in apps)
    shown_pct = sum(a.pct_sys for a in shown)
    total_nproc = sum(a.nproc for a in apps)
    shown_nproc = sum(a.nproc for a in shown)
    cov = Coverage(
        total_pct_sys=total_pct,
        shown_pct_sys=shown_pct,
        tail_pct_sys=total_pct - shown_pct,
        tail_nproc=total_nproc - shown_nproc,
    )
    return shown, cov


def collect(top_n: int | None = None, sample_interval: float = 0.3) -> list[HotProc]:
    """Return processes ranked by CPU%, descending.

    ``top_n=None`` returns *every* non-zero process so callers can aggregate
    by app without losing the long tail; pass an int to truncate (kept for
    ``cool status --json`` and existing call sites).

    ``sample_interval`` controls how long we wait between priming and
    reading cpu_percent. Shorter = faster but noisier; 0.3s matches
    ``procs.collect``'s order of magnitude.
    """
    ncpu = psutil.cpu_count(logical=True) or 1

    # First pass: prime CPU accounting for every process. psutil requires
    # at least one prior call before cpu_percent() returns a real value.
    primed: list[psutil.Process] = []
    for p in psutil.process_iter(["pid"]):
        try:
            p.cpu_percent(None)
            primed.append(p)
        except PROC_ERRORS:
            continue

    time.sleep(sample_interval)

    # Second pass: read CPU% and snapshot metadata. Skip 0% procs — the
    # panel only cares about hot ones and dropping them keeps the sort small.
    now = time.time()
    rows: list[HotProc] = []
    for p in primed:
        try:
            with p.oneshot():
                raw = p.cpu_percent(None)
                if raw <= 0.0:
                    continue
                cpu = raw / ncpu
                mem = p.memory_info().rss
                ct = p.create_time()
                username = p.username()
                name = p.name()
                # exe() raises a wider set of errors than PROC_ERRORS
                # (AccessDenied on SIP binaries, AttributeError on test
                # fakes); it's purely for grouping, so a miss is non-fatal.
                try:
                    exe = p.exe() or ""
                except Exception:  # noqa: BLE001 — exe is best-effort, see above
                    exe = ""
                try:
                    cmd = " ".join(p.cmdline())
                except PROC_ERRORS:
                    cmd = name
        except PROC_ERRORS:
            continue
        rows.append(
            HotProc(
                pid=p.pid,
                name=name,
                cmdline=cmd,
                cpu_percent=cpu,
                rss=mem,
                user=username,
                create_time=ct,
                age=max(0.0, now - ct),
                exe=exe,
            )
        )

    rows.sort(key=lambda h: (-h.cpu_percent, h.pid))
    return rows if top_n is None else rows[:top_n]

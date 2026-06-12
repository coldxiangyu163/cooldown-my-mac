"""Detect orphaned automation browsers and leaked launcher processes.

AI coding agents drive headless / remote-controlled browsers via tools like
agent-browser, Puppeteer, and Playwright. Those tools spawn Chrome on a
throwaway profile (``--user-data-dir`` under ``/var/folders``) and are
supposed to tear it down when the session ends — but a crashed or abandoned
session leaves the browser (and sometimes the launcher itself) resident for
days. That is exactly the "runaway from an AI coding session" cooldown
exists to clean up, yet it is neither an AI CLI nor a multiplexer, so the
existing reap path misses it.

This collector is read-only: it *identifies* candidates; killing stays in
``actions.reap``. The user's real browser (default profile, no automation
markers, not parented to an automation tool) is never classified as a
candidate.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING

import psutil

from ..util import PROC_ERRORS
from .hot_procs import group_key
from .procs import ProcInfo

if TYPE_CHECKING:  # HotApp only needed for a type hint; avoid an import cycle
    from .hot_procs import HotApp

# Flags Chrome/Chromium only carries when something is driving it.
AUTOMATION_FLAGS = (
    "--remote-debugging-port",
    "--remote-debugging-pipe",
    "--headless",
    "--enable-automation",
    "--test-type",
)

# (substring found in --user-data-dir, canonical tool name)
_TOOL_MARKERS: tuple[tuple[str, str], ...] = (
    ("agent-browser", "agent-browser"),
    ("puppeteer", "puppeteer"),
    ("ms-playwright", "playwright"),
    ("playwright", "playwright"),
)
# A user-data-dir under one of these is a throwaway profile, never the real
# browser's (which lives under ~/Library/Application Support/...).
_TEMP_PREFIXES = ("/var/folders/", "/private/var/folders/", "/tmp/", "/private/tmp/")
# Launcher process-name fragments that should not outlive their browser.
_LAUNCHER_NAMES = ("agent-browser", "chromedriver", "geckodriver")

_UDD_RE = re.compile(r"--user-data-dir[=\s]+(\S+)")


@dataclass
class BrowserOrigin:
    tool: str  # "agent-browser" | "puppeteer" | "playwright" | "automation" | <parent>
    profile_dir: str  # the throwaway --user-data-dir, when present
    reason: str  # "temp-profile" | "automation-flag" | "automation-parent"


def is_chromium(name: str, exe: str) -> bool:
    hay = f"{name} {exe}".lower()
    return "chrome" in hay or "chromium" in hay


def is_firefox(name: str, exe: str) -> bool:
    return "firefox" in f"{name} {exe}".lower()


def is_browser(name: str, exe: str) -> bool:
    """A chromium- or firefox-family browser — the kinds an automation launcher
    (chromedriver / geckodriver / agent-browser) keeps alive. Used to spare a
    launcher that is still managing a live browser, so an active Selenium /
    Playwright session is never mistaken for a leaked launcher."""
    return is_chromium(name, exe) or is_firefox(name, exe)


def user_data_dir(cmdline: str) -> str:
    m = _UDD_RE.search(cmdline)
    return m.group(1) if m else ""


def _segment_marker_tool(udd: str) -> str | None:
    """Return the automation tool whose marker *begins a path segment* of the
    profile dir (".../agent-browser-chrome-abc"), else None.

    Segment-anchored on purpose: a loose substring match would read a real
    profile living under e.g. ``~/Library/.../my-agent-browser-notes/`` as a
    throwaway automation profile and make the user's real browser reapable.
    """
    for seg in udd.lower().split("/"):
        for marker, tool in _TOOL_MARKERS:
            if seg.startswith(marker):
                return tool
    return None


def is_temp_profile(udd: str) -> bool:
    if _segment_marker_tool(udd):
        return True
    return udd.lower().startswith(_TEMP_PREFIXES)


def is_helper(cmdline: str) -> bool:
    """True for a Chromium *child* process (renderer / gpu-process / utility /
    zygote / crashpad). Such processes carry ``--type=`` and are torn down by
    their parent browser, so they are never an independent leftover root — the
    killer reaps them via the root's subtree instead.
    """
    return "--type=" in cmdline


def automation_tool(cmdline: str) -> str | None:
    """Return a tool label if this chromium cmdline looks driven by
    automation, else None. Pure cmdline inspection, no psutil."""
    udd = user_data_dir(cmdline)
    tool = _segment_marker_tool(udd)
    if tool:
        return tool
    if udd and is_temp_profile(udd):
        return "automation"
    if any(f in cmdline for f in AUTOMATION_FLAGS):
        return "automation"
    return None


def browser_aware_key(exe: str, cmdline: str, name: str) -> str:
    """Group key that splits an automation / temp-profile chromium into its
    own group, so it never merges with — or mis-flags — the user's real
    browser. Falls back to the generic ``hot_procs.group_key``."""
    base = group_key(exe, cmdline, name)
    if is_chromium(name, exe):
        tool = automation_tool(cmdline)
        if tool:
            return f"{base} ({tool})"
    return base


def classify_browser_origin(name: str, exe: str, cmdline: str, parent_name: str = "") -> BrowserOrigin | None:
    """Classify a single process. None unless it is an automation browser.

    The user's real browser (default profile, no automation flags, not
    parented to an automation tool) never matches.
    """
    if not is_chromium(name, exe):
        return None
    udd = user_data_dir(cmdline)
    tool = automation_tool(cmdline)
    if udd and is_temp_profile(udd):
        return BrowserOrigin(tool or "automation", udd, "temp-profile")
    if any(f in cmdline for f in AUTOMATION_FLAGS):
        return BrowserOrigin(tool or "automation", udd, "automation-flag")
    if parent_name and any(m in parent_name.lower() for m in _LAUNCHER_NAMES):
        return BrowserOrigin(parent_name, udd, "automation-parent")
    return None


def annotate_origins(apps: list[HotApp]) -> None:
    """Fill ``HotApp.origin`` for automation-browser groups. Pure: works off
    the already-collected ``HotProc`` fields, no extra psutil calls.

    Because ``browser_aware_key`` puts automation procs in their own group,
    the user's real browser group contains only default-profile members and
    therefore never classifies — the guard holds by construction.
    """
    for app in apps:
        for member in app.procs:
            origin = classify_browser_origin(member.name, member.exe, member.cmdline)
            if origin is not None:
                app.origin = origin
                break


def _rss(proc: psutil.Process) -> int:
    try:
        return proc.memory_info().rss
    except (OSError, *PROC_ERRORS):
        return 0


def _str_call(proc: psutil.Process, attr: str) -> str:
    try:
        return getattr(proc, attr)() or ""
    except (OSError, *PROC_ERRORS):
        return ""


def collect(*, leak_age_seconds: float = 1800.0, sample_interval: float = 0.3) -> list[ProcInfo]:
    """Return reapable leftovers as ``ProcInfo`` (``kind='automation-browser'``):

    1. Root automation-browser processes. Chrome's helper fleet
       (``--type=renderer`` / gpu / utility) is deduped away — it dies with
       its parent, so we surface only the root and let ``actions.reap`` tear
       down the subtree. An *orphaned* helper (its browser parent gone) is
       still surfaced so it gets cleaned up.
    2. Launcher processes (agent-browser / chromedriver / ...) that have
       outlived their browser by ``leak_age_seconds`` with no live browser
       child.

    CPU% is sampled across ``sample_interval`` (set ``0.0`` to skip the wait)
    so callers can see which leftover is actually cooking the CPU; ``ppid`` and
    ``create_time`` are carried so the killer can validate identity and the
    daemon can flag launchd-reparented orphans.

    Read-only — killing is the caller's job via ``actions.reap``.
    """
    now = time.time()
    procs = list(psutil.process_iter(["pid", "name", "ppid"]))
    by_pid = {p.pid: p for p in procs}

    # Pass 1: classify candidates and prime CPU accounting (psutil needs a
    # prior cpu_percent() call before it returns a real value).
    candidates: list[tuple[psutil.Process, str, str, int, float, float, str]] = []
    for p in procs:
        try:
            name = p.info.get("name") or ""
            ppid = p.info.get("ppid") or 0
            cmdline = " ".join(p.cmdline() or [])
            ct = p.create_time()
        except PROC_ERRORS:
            continue
        exe = _str_call(p, "exe")
        age = max(0.0, now - ct)
        parent = by_pid.get(ppid)
        parent_name = (parent.info.get("name") if parent else "") or ""

        origin = classify_browser_origin(name, exe, cmdline, parent_name=parent_name)
        if origin is not None:
            # Skip helpers whose parent is still a live browser: the root we
            # already queued will take them down via its subtree. Keep helpers
            # whose browser parent is gone (orphaned) so nothing is missed.
            if is_helper(cmdline) and parent is not None and is_chromium(parent_name, ""):
                continue
            note = _note(f"{origin.tool} · {origin.reason}", ppid)
            candidates.append((p, name, cmdline, ppid, ct, age, note))
            _prime_cpu(p)
            continue

        if any(m in name.lower() for m in _LAUNCHER_NAMES) and age >= leak_age_seconds:
            try:
                children = p.children(recursive=True)
            except PROC_ERRORS:
                children = []
            has_browser = any(is_browser(_str_call(c, "name"), "") for c in children)
            if not has_browser:
                note = _note("leaked launcher · no browser child", ppid)
                candidates.append((p, name, cmdline, ppid, ct, age, note))
                _prime_cpu(p)

    if sample_interval > 0 and candidates:
        time.sleep(sample_interval)

    # Pass 2: read CPU% (normalized to a single-core share) and synthesize.
    ncpu = psutil.cpu_count(logical=True) or 1
    out: list[ProcInfo] = []
    for p, name, cmdline, ppid, ct, age, note in candidates:
        out.append(_synth(p, name, cmdline, ppid, ct, _read_cpu(p, ncpu), age, note))
    return out


def _note(reason: str, ppid: int) -> str:
    """A process reparented to launchd (ppid<=1) will never be cleaned up by
    its launcher, so flag it as an orphan — the ``ppid`` signal the daemon and
    reap UI surface."""
    return f"{reason} · orphan" if ppid <= 1 else reason


def _prime_cpu(p: psutil.Process) -> None:
    try:
        p.cpu_percent(None)
    except (OSError, *PROC_ERRORS):
        pass


def _read_cpu(p: psutil.Process, ncpu: int) -> float:
    try:
        return p.cpu_percent(None) / ncpu
    except (OSError, *PROC_ERRORS):
        return 0.0


def _synth(
    p: psutil.Process,
    name: str,
    cmdline: str,
    ppid: int,
    create_time: float,
    cpu_percent: float,
    age: float,
    note: str,
) -> ProcInfo:
    # Prefix the origin + orphan classification onto the displayed cmdline so
    # it actually reaches the user (the reap table's only text column) and the
    # oplog audit entry, instead of being discarded behind a non-empty cmdline.
    display = f"{note} — {cmdline}" if cmdline else note
    return ProcInfo(
        pid=p.pid,
        ppid=ppid,
        kind="automation-browser",
        name=name,
        cmdline=display,
        rss=_rss(p),
        cpu_percent=cpu_percent,
        create_time=create_time,
        age=age,
        tty=None,
        user=_str_call(p, "username"),
        # The reap table shows an "idle" column; for a leftover the staleness
        # (age) is the meaningful number, so surface it there.
        idle_seconds=age,
    )

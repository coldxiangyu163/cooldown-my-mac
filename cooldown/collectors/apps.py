"""Heavy background / IM app inventory (main process detection only)."""
from __future__ import annotations

import time
from dataclasses import dataclass, field

import psutil

from ..util import PROC_ERRORS

# Classification table: kind -> list of .app bundle folder names or main
# executable names we expect to see. The first entry in each tuple is the
# canonical display name for the app. The second `needles` tuple matches
# substrings inside the cmdline/path that uniquely identify the main
# process of the app (as opposed to Helper / Renderer subprocesses).
APP_TABLE: list[tuple[str, str, tuple[str, ...], tuple[str, ...]]] = [
    # kind, display, cmdline/path markers, process name hints
    ("wechat", "WeChat", ("/applications/wechat.app/contents/macos/wechat",), ("wechat",)),
    ("dingtalk", "DingTalk", ("/applications/dingtalk.app/contents/macos/dingtalk",), ("dingtalk",)),
    ("lark", "Lark", ("/applications/lark.app/contents/macos/lark",), ("lark",)),
    (
        "todesk",
        "ToDesk",
        ("/applications/todesk.app/contents/macos/todesk", "todesk_service"),
        ("todesk", "todesk_service"),
    ),
    ("paste", "Paste", ("/applications/paste.app/contents/macos/paste",), ("paste",)),
    ("raycast", "Raycast", ("/applications/raycast.app/contents/macos/raycast",), ("raycast",)),
    ("slack", "Slack", ("/applications/slack.app/contents/macos/slack",), ("slack",)),
    ("telegram", "Telegram", ("/applications/telegram.app/contents/macos/telegram",), ("telegram",)),
    ("qq", "QQ", ("/applications/qq.app/contents/macos/qq",), ("qq",)),
]

# Substrings in cmdline that mark a process as an Electron/Chromium child.
_HELPER_MARKERS = ("helper", "renderer", "--type=", "gpu-process", "crashpad")


@dataclass
class AppInfo:
    kind: str
    app_name: str
    display_name: str
    pid: int
    rss: int
    cpu_percent: float
    ppid: int
    frozen: bool = field(default=False)


def _is_helper(name: str, cmdline: str) -> bool:
    hay = f"{name} {cmdline}".lower()
    return any(marker in hay for marker in _HELPER_MARKERS)


def _classify(name: str, cmdline: str) -> tuple[str, str] | None:
    """Return (kind, display_name) if this looks like the MAIN process."""
    hay_cmd = cmdline.lower()
    hay_name = name.lower()

    if _is_helper(name, cmdline):
        return None

    for kind, display, path_markers, name_hints in APP_TABLE:
        # Path-based match is the strongest: it pins us to the main binary
        # in the .app bundle (excludes Helpers which live in Frameworks/).
        if any(marker in hay_cmd for marker in path_markers):
            return kind, display
        # Fallback: exact name match (helps when cmdline is hidden).
        if hay_name in name_hints:
            # Still require that cmdline does not look like a helper.
            return kind, display
    return None


def _sample(procs: list[psutil.Process], interval: float = 0.2) -> dict[int, float]:
    """Prime and sample CPU percent for a list of processes."""
    for p in procs:
        try:
            p.cpu_percent(None)
        except PROC_ERRORS:
            continue
    time.sleep(interval)
    out: dict[int, float] = {}
    ncpu = psutil.cpu_count(logical=True) or 1
    for p in procs:
        try:
            out[p.pid] = p.cpu_percent(None) / ncpu
        except PROC_ERRORS:
            continue
    return out


def collect(*, freeze_sample_interval: float = 0.4) -> list[AppInfo]:
    """Return one AppInfo per detected heavy app (main process only)."""
    groups: dict[str, list[tuple[psutil.Process, str]]] = {}

    for p in psutil.process_iter(["pid", "name", "ppid"]):
        try:
            name = p.info["name"] or ""
            try:
                cmd = " ".join(p.cmdline() or [])
            except PROC_ERRORS:
                cmd = ""
            classified = _classify(name, cmd)
            if classified is None:
                continue
            kind, display = classified
            groups.setdefault(kind, []).append((p, display))
        except PROC_ERRORS:
            continue

    # First CPU sample.
    all_procs = [p for entries in groups.values() for p, _ in entries]
    cpu_a = _sample(all_procs, interval=0.2)
    # Second sample for frozen detection (SIGSTOP'd processes yield 0% twice).
    cpu_b = _sample(all_procs, interval=freeze_sample_interval)

    out: list[AppInfo] = []
    for kind, entries in groups.items():
        # Pick "main" process: smallest pid within group (the OS spawns the
        # main app first, helpers later). This also avoids Login Items
        # helper binaries if they somehow classified through name-only.
        rep_proc, display = min(entries, key=lambda e: e[0].pid)
        try:
            with rep_proc.oneshot():
                ppid = rep_proc.ppid()
                rss = rep_proc.memory_info().rss
                name = rep_proc.name()
        except PROC_ERRORS:
            continue
        cpu = cpu_b.get(rep_proc.pid, cpu_a.get(rep_proc.pid, 0.0))
        # Frozen heuristic: both samples were ~0% AND process shows no cpu
        # accumulation. We can't read SIGSTOP state portably, so this is
        # only an approximation.
        frozen = (
            cpu_a.get(rep_proc.pid, 0.0) < 0.01
            and cpu_b.get(rep_proc.pid, 0.0) < 0.01
        )
        out.append(
            AppInfo(
                kind=kind,
                app_name=name,
                display_name=display,
                pid=rep_proc.pid,
                rss=rss,
                cpu_percent=cpu,
                ppid=ppid,
                frozen=frozen,
            )
        )

    out.sort(key=lambda a: (-a.rss, a.kind))
    return out

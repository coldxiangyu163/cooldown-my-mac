"""Walk up the process tree and identify a process's meaningful launcher.

A "launcher" is the first ancestor we recognize as something more
informative than a bare shell: a multiplexer (tmux / cmux / zellij), an AI
CLI (droid / codex / claude / opencode / ...), an IDE (vscode / cursor /
jetbrains), a terminal app (iTerm / Ghostty / Warp / ...), or launchd.

This is used by `cool dev` to answer "who started this node process?".
"""
from __future__ import annotations

import re
from dataclasses import dataclass

import psutil

from ..util import PROC_ERRORS

# Ordered list: first match wins. Each entry is
# (kind, predicate) where predicate returns True if the ancestor matches.
# We keep it inline-free-functions to make the control flow explicit.

# Terminal .app bundle names → kind. Matched via a case-sensitive regex on
# the exe / cmdline path.
_TERMINAL_APPS: tuple[tuple[str, str], ...] = (
    ("warp", "Warp"),
    ("ghostty", "Ghostty"),
    ("alacritty", "Alacritty"),
    ("wezterm", "WezTerm"),
    ("kitty", "kitty"),
    ("iterm", "iTerm"),
    ("terminal", "Terminal"),
    ("kaku", "Kaku"),
)

# Shell basenames — we detect but keep walking.
_SHELL_NAMES = {"bash", "zsh", "sh", "fish", "dash", "ksh", "tcsh"}


@dataclass
class Launcher:
    kind: str
    label: str
    pid: int | None


_UNKNOWN = Launcher(kind="unknown", label="unknown", pid=None)


def _safe_fields(proc: psutil.Process) -> tuple[str, str, str, int]:
    """Return (name, exe, cmdline, ppid) swallowing psutil errors."""
    try:
        name = proc.name() or ""
    except PROC_ERRORS:
        name = ""
    try:
        exe = proc.exe() or ""
    except PROC_ERRORS:
        exe = ""
    try:
        cmdline = " ".join(proc.cmdline() or [])
    except PROC_ERRORS:
        cmdline = ""
    try:
        ppid = proc.ppid()
    except PROC_ERRORS:
        ppid = 0
    return name, exe, cmdline, ppid


def walk(pid: int, *, max_depth: int = 10) -> list[psutil.Process]:
    """Return the list of ancestor processes of `pid` (excluding pid itself
    and pid 0). Truncated at `max_depth`."""
    out: list[psutil.Process] = []
    try:
        p = psutil.Process(pid)
    except PROC_ERRORS:
        return out
    try:
        parent = p.parent()
    except PROC_ERRORS:
        return out
    depth = 0
    while parent is not None and parent.pid != 0 and depth < max_depth:
        out.append(parent)
        try:
            parent = parent.parent()
        except PROC_ERRORS:
            break
        depth += 1
    return out


def _match_app(path: str) -> tuple[str, str] | None:
    """Return (kind, label) if `path` points into one of the known .app
    bundles. Uses a case-insensitive /Applications/<Name>.app/ match so
    user-installed copies under ~/Applications also count.
    """
    if not path:
        return None
    # Examples of paths to match:
    #   /Applications/Warp.app/Contents/MacOS/stable
    #   /Applications/iTerm.app/Contents/MacOS/iTerm2
    m = re.search(r"/([A-Za-z0-9_]+)\.app/", path)
    if not m:
        return None
    bundle = m.group(1).lower()
    for kind, label in _TERMINAL_APPS:
        # Accept exact or prefix match so "iterm2" still maps to iterm.
        if bundle == kind or bundle.startswith(kind):
            return kind, label
    return None


def classify_ancestor(proc: psutil.Process) -> Launcher | None:
    """Classify a single process into a `Launcher`.

    First match wins. Returns None if we cannot place it into a known
    category (caller will normally keep walking upward).
    """
    name, exe, cmdline, ppid = _safe_fields(proc)
    if not name and not exe and not cmdline:
        return None

    hay = f"{name} {cmdline}".lower()
    exe_lower = exe.lower()

    # --- Multiplexers -------------------------------------------------
    if "tmux" in hay or "/tmux" in exe_lower:
        return Launcher(kind="tmux", label="tmux", pid=proc.pid)
    if "cmux" in hay or "/cmux" in exe_lower:
        return Launcher(kind="cmux", label="cmux", pid=proc.pid)
    if "zellij" in hay or "/zellij" in exe_lower:
        return Launcher(kind="zellij", label="zellij", pid=proc.pid)

    # --- AI CLIs ------------------------------------------------------
    for kind in ("droid", "codex", "claude", "opencode", "nanobot", "hermes"):
        if kind in hay:
            return Launcher(kind=kind, label=kind, pid=proc.pid)

    # --- IDEs (path-based) -------------------------------------------
    if "Visual Studio Code" in exe or "Code Helper" in exe or "Visual Studio Code" in cmdline:
        return Launcher(kind="vscode", label="VS Code", pid=proc.pid)
    if "Cursor.app" in exe or "Cursor.app" in cmdline:
        return Launcher(kind="cursor", label="Cursor", pid=proc.pid)
    if "DataGrip.app" in exe or "DataGrip.app" in cmdline:
        return Launcher(kind="datagrip", label="DataGrip", pid=proc.pid)
    for jb in ("IntelliJ", "PyCharm", "WebStorm", "GoLand", "RubyMine", "CLion"):
        if jb in exe or jb in cmdline:
            return Launcher(kind="jetbrains", label=jb, pid=proc.pid)

    # --- Terminals (.app) --------------------------------------------
    bundle_match = _match_app(exe) or _match_app(cmdline)
    if bundle_match is not None:
        kind, label = bundle_match
        return Launcher(kind=kind, label=label, pid=proc.pid)

    # --- Finder -------------------------------------------------------
    if "Finder.app" in exe or "Finder.app" in cmdline:
        return Launcher(kind="finder", label="Finder", pid=proc.pid)

    # --- launchd (only when directly parent=1) -----------------------
    if ppid == 1 and name == "launchd":
        return Launcher(kind="launchd", label="launchd", pid=proc.pid)
    if proc.pid == 1 and name == "launchd":
        return Launcher(kind="launchd", label="launchd", pid=proc.pid)

    # --- Shells -------------------------------------------------------
    # We mark it so find_launcher can skip past, but do not stop here.
    if name in _SHELL_NAMES:
        return Launcher(kind="shell", label=name, pid=proc.pid)

    return None


def find_launcher(pid: int) -> Launcher:
    """Walk upward from `pid` and return the first non-shell, recognized
    ancestor.

    If we reach pid 1 without any match AND the direct ppid of `pid` is 1
    (i.e., this process is a true orphan attached to launchd), we return
    ``Launcher("launchd", "launchd (orphan)", 1)``. Otherwise we return
    ``Launcher("unknown", "unknown", None)``.
    """
    try:
        target = psutil.Process(pid)
    except PROC_ERRORS:
        return Launcher(kind="unknown", label="unknown", pid=None)

    try:
        direct_ppid = target.ppid()
    except PROC_ERRORS:
        direct_ppid = 0

    ancestors = walk(pid)
    for anc in ancestors:
        try:
            guess = classify_ancestor(anc)
        except PROC_ERRORS:
            continue
        if guess is None:
            continue
        if guess.kind == "shell":
            # keep walking
            continue
        return guess

    # Exhausted the chain.
    if direct_ppid == 1:
        return Launcher(kind="launchd", label="launchd (orphan)", pid=1)
    return Launcher(kind="unknown", label="unknown", pid=None)

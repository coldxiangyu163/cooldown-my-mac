"""Audit the user's launchd agents and daemons.

Parses ``launchctl list`` (fast, ~500 entries typical), classifies each
label as ``apple``/``homebrew``/``third-party``/``user``/``unknown`` and
locates the backing plist on disk so the ``actions.launchd`` module can
bootstrap/bootout it cleanly.
"""
from __future__ import annotations

import fnmatch
import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

Domain = Literal["system", "user", "gui"]
Category = Literal["apple", "homebrew", "third-party", "user", "unknown"]

_PLIST_SEARCH_DIRS: tuple[str, ...] = (
    "~/Library/LaunchAgents",
    "/Library/LaunchAgents",
    "/Library/LaunchDaemons",
    "/System/Library/LaunchAgents",
    "/System/Library/LaunchDaemons",
)

# Known noisy / often-unnecessary labels. Kept small and honest — we prefer
# false negatives to false positives when flagging user workloads.
_NOISY_PATTERNS: tuple[str, ...] = (
    "com.tencent.WeChat*",
    "com.alibaba.DingTalk*",
    "com.bytedance.lark*",
    "com.oray.sunlogin.*",
    "com.todesk.*",
)


@dataclass
class LaunchdEntry:
    label: str
    domain: Domain
    pid: int | None
    last_exit_status: int | None
    path: str | None  # absolute path to the plist, if we could resolve it
    category: Category
    enabled: bool


def _run(cmd: list[str], *, timeout: float = 3.0) -> str:
    try:
        r = subprocess.run(cmd, check=False, capture_output=True, text=True, timeout=timeout)
    except (subprocess.SubprocessError, FileNotFoundError):
        return ""
    return r.stdout or ""


def _build_plist_index() -> dict[str, str]:
    """Index ``<label>.plist`` → absolute path across all standard dirs."""
    index: dict[str, str] = {}
    for raw in _PLIST_SEARCH_DIRS:
        root = Path(os.path.expanduser(raw))
        if not root.is_dir():
            continue
        try:
            for p in root.iterdir():
                if p.suffix == ".plist":
                    label = p.stem
                    # First write wins to keep resolution deterministic and
                    # prefer user-space locations.
                    index.setdefault(label, str(p))
        except OSError:
            continue
    return index


def _domain_for(path: str | None, label: str) -> Domain:
    if path is None:
        # launchctl list without -D is the user/gui domain.
        return "gui"
    if path.startswith("/System/Library/LaunchDaemons") or path.startswith("/Library/LaunchDaemons"):
        return "system"
    if path.startswith(os.path.expanduser("~/Library/LaunchAgents")):
        return "user"
    return "gui"


def _classify(label: str, path: str | None) -> Category:
    if label.startswith("com.apple.") and path and path.startswith("/System/"):
        return "apple"
    home_agents = os.path.expanduser("~/Library/LaunchAgents")
    if (
        path
        and (
            path.startswith("/Library/LaunchDaemons")
            or path.startswith("/Library/LaunchAgents")
        )
        and ("homebrew" in label.lower() or "homebrew" in path.lower())
    ):
        return "homebrew"
    if path and path.startswith("/System/"):
        return "apple"
    if path and path.startswith(home_agents):
        return "user"
    if path:
        return "third-party"
    # No plist found. Fall back to label-only heuristics.
    if label.startswith("com.apple."):
        return "apple"
    return "unknown"


_LINE_RE = re.compile(r"^\s*(-|\d+)\s+(-|-?\d+)\s+(\S.*?)\s*$")


def _parse_list(text: str) -> list[tuple[int | None, int | None, str]]:
    rows: list[tuple[int | None, int | None, str]] = []
    for line in text.splitlines():
        if not line.strip() or line.startswith("PID"):
            continue
        m = _LINE_RE.match(line)
        if not m:
            continue
        pid_raw, status_raw, label = m.group(1), m.group(2), m.group(3)
        pid = None if pid_raw == "-" else int(pid_raw)
        status = None if status_raw == "-" else int(status_raw)
        rows.append((pid, status, label))
    return rows


def collect(*, list_output: str | None = None) -> list[LaunchdEntry]:
    """Return a list of ``LaunchdEntry`` for every label ``launchctl`` knows
    about in the calling user's domain.

    The ``list_output`` kwarg exists for tests — when provided we skip the
    subprocess and parse the supplied text directly.
    """
    raw = list_output if list_output is not None else _run(["launchctl", "list"])
    index = _build_plist_index()
    entries: list[LaunchdEntry] = []
    for pid, status, label in _parse_list(raw):
        path = index.get(label)
        category = _classify(label, path)
        domain = _domain_for(path, label)
        entries.append(
            LaunchdEntry(
                label=label,
                domain=domain,
                pid=pid,
                last_exit_status=status,
                path=path,
                category=category,
                enabled=True,  # launchctl list only shows loaded jobs
            )
        )
    return entries


def _is_noisy(label: str) -> bool:
    return any(fnmatch.fnmatch(label, pat) for pat in _NOISY_PATTERNS)


def suspicious(entries: list[LaunchdEntry]) -> list[LaunchdEntry]:
    """Return a subset of entries worth a human review.

    Heuristics:
    * any label matching ``_NOISY_PATTERNS`` (IM clients, remote-control).
    * third-party entries with a non-zero last_exit_status (crash-loopers).
    """
    out: list[LaunchdEntry] = []
    for e in entries:
        if e.category == "apple":
            continue
        if _is_noisy(e.label):
            out.append(e)
            continue
        if (
            e.category in {"third-party", "user", "unknown"}
            and e.last_exit_status is not None
            and e.last_exit_status != 0
        ):
            out.append(e)
    # Deterministic order: crash-loopers first, then noisy labels.
    out.sort(key=lambda e: (e.last_exit_status or 0, e.label), reverse=True)
    return out


def group_by_category(entries: list[LaunchdEntry]) -> dict[Category, list[LaunchdEntry]]:
    out: dict[Category, list[LaunchdEntry]] = {}
    for e in entries:
        out.setdefault(e.category, []).append(e)
    for v in out.values():
        v.sort(key=lambda x: x.label)
    return out

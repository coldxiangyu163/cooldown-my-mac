"""Resolve a process to the project directory it is running inside.

A "project" is the nearest ancestor directory of a process's cwd that
contains one of the well-known marker files (``package.json``,
``pyproject.toml``, a ``.git`` directory, ...).

We use ``psutil.Process.cwd()`` as the primary source of truth, falling
back to ``lsof -Fn -a -d cwd`` when psutil raises ``AccessDenied`` (e.g.,
processes owned by other users or with SIP-protected cwds).
"""
from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

import psutil

from ..util import PROC_ERRORS

# Ordered by priority. A directory is a project root when it contains
# at least one of these entries (file OR directory for ``.git``).
MARKERS: tuple[str, ...] = (
    ".git",
    "package.json",
    "pyproject.toml",
    "requirements.txt",
    "setup.py",
    "Cargo.toml",
    "go.mod",
    "Gemfile",
    "pom.xml",
    "build.gradle",
    "composer.json",
    "Pipfile",
    "poetry.lock",
    "deno.json",
    "bun.lockb",
)


@dataclass
class Project:
    root: Path
    name: str
    markers: list[str]


def _detect_markers(directory: Path) -> list[str]:
    """Return the subset of known markers present at `directory`, in the
    canonical priority order."""
    found: list[str] = []
    for m in MARKERS:
        try:
            if (directory / m).exists():
                found.append(m)
        except OSError:
            continue
    return found


def find_root(cwd: str | Path, *, max_depth: int = 10) -> Project | None:
    """Walk up from `cwd` (inclusive) at most `max_depth` levels and return
    the first directory that contains at least one project marker."""
    if cwd is None:
        return None
    try:
        path = Path(cwd).resolve()
    except (OSError, RuntimeError):
        return None

    current: Path | None = path
    depth = 0
    while current is not None and depth <= max_depth:
        try:
            is_dir = current.is_dir()
        except OSError:
            is_dir = False
        if is_dir:
            markers = _detect_markers(current)
            if markers:
                return Project(root=current, name=current.name, markers=markers)
        parent = current.parent
        if parent == current:
            break
        current = parent
        depth += 1
    return None


def _cwd_via_lsof(pid: int) -> str | None:
    """Fallback for processes whose cwd psutil cannot read directly."""
    try:
        res = subprocess.run(
            ["lsof", "-p", str(pid), "-Fn", "-a", "-d", "cwd"],
            capture_output=True,
            text=True,
            timeout=1.0,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if res.returncode != 0:
        return None
    # lsof -F outputs one field per line, prefixed by its type letter.
    # We want the `n` line (name / path).
    for line in res.stdout.splitlines():
        if line.startswith("n") and len(line) > 1:
            return line[1:].strip() or None
    return None


def get_cwd(pid: int) -> str | None:
    """Return the cwd of `pid`. Best-effort: returns None on any failure."""
    try:
        p = psutil.Process(pid)
    except PROC_ERRORS:
        return None
    try:
        cwd = p.cwd()
        return cwd or None
    except psutil.AccessDenied:
        return _cwd_via_lsof(pid)
    except PROC_ERRORS:
        return None
    except RuntimeError:
        return None


def lookup(pid: int) -> Project | None:
    """Return the Project a process is running in, or None."""
    cwd = get_cwd(pid)
    if not cwd:
        return None
    return find_root(cwd)

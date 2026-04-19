"""Dev-stack process inventory: node / python / ruby / go / rust / java /
php / deno / bun / dotnet processes enriched with project + launcher +
framework attribution.

This is the engine behind ``cool dev``. See :mod:`cooldown.ui.dev` for
the presentation layer.
"""
from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from pathlib import Path

import psutil

from . import ancestry as ancestry_mod
from . import project as project_mod
from .ancestry import Launcher
from .project import Project

# ---------------------------------------------------------------------------
# Language patterns. Order matters: the first language whose needles appear
# in (name + cmdline) wins.
# ---------------------------------------------------------------------------
LANG_PATTERNS: list[tuple[str, tuple[str, ...]]] = [
    # Keep node before python so "node /path/to/python/.bin" quirks don't
    # end up misclassified.
    ("node", ("node", "nodejs", "npm", "pnpm", "yarn", "npx", "corepack")),
    ("deno", ("deno",)),
    ("bun", ("bun",)),
    ("python", ("python", "python3", "uvicorn", "gunicorn", "celery", "jupyter", "streamlit", "pytest")),
    ("ruby", ("ruby", "rails", "rake", "bundle", "puma", "sidekiq")),
    ("go", ("go run", "/go/bin/", "gopls")),
    ("rust", ("cargo", "rustc", "/target/debug/", "/target/release/", "rust-analyzer")),
    ("java", ("java", "gradle", "mvn", "kotlin")),
    ("php", ("php", "php-fpm", "artisan")),
    ("dotnet", ("dotnet", "mono")),
]

# Framework needles, grouped by which lang(s) they are relevant for.
# Each tuple is (framework_label, (needles,), frozenset(langs_allowed)).
FRAMEWORK_PATTERNS: list[tuple[str, tuple[str, ...], frozenset[str]]] = [
    # --- node ecosystem ---------------------------------------------
    ("next", ("next-server", "next dev", "next start", "next-router-worker"), frozenset({"node"})),
    ("vite", ("vite",), frozenset({"node", "bun"})),
    ("webpack", ("webpack",), frozenset({"node"})),
    ("rollup", ("rollup",), frozenset({"node"})),
    ("esbuild", ("esbuild",), frozenset({"node"})),
    ("nest", ("nest start", "@nestjs/"), frozenset({"node"})),
    ("nuxt", ("nuxt",), frozenset({"node"})),
    ("tsx", ("tsx ",), frozenset({"node"})),
    ("ts-node", ("ts-node",), frozenset({"node"})),
    ("nodemon", ("nodemon",), frozenset({"node"})),
    ("jest", ("jest",), frozenset({"node"})),
    ("mocha", ("mocha",), frozenset({"node"})),
    # --- python -----------------------------------------------------
    ("uvicorn", ("uvicorn",), frozenset({"python"})),
    ("gunicorn", ("gunicorn",), frozenset({"python"})),
    ("flask", ("flask run", "flask ", "FLASK_APP"), frozenset({"python"})),
    ("django", ("manage.py runserver", "django-admin", "daphne"), frozenset({"python"})),
    ("fastapi", ("fastapi",), frozenset({"python"})),
    ("celery", ("celery",), frozenset({"python"})),
    ("jupyter", ("jupyter",), frozenset({"python"})),
    ("streamlit", ("streamlit",), frozenset({"python"})),
    ("pytest", ("pytest",), frozenset({"python"})),
    # --- ruby -------------------------------------------------------
    ("rails", ("rails ", "bin/rails", "rails server"), frozenset({"ruby"})),
    ("puma", ("puma",), frozenset({"ruby"})),
    ("sidekiq", ("sidekiq",), frozenset({"ruby"})),
    # --- go ---------------------------------------------------------
    ("go run", ("go run",), frozenset({"go"})),
    # --- rust -------------------------------------------------------
    ("cargo run", ("cargo run", "cargo watch", "cargo test"), frozenset({"rust"})),
    # --- java -------------------------------------------------------
    ("spring", ("spring-boot", "org.springframework"), frozenset({"java"})),
    ("gradle", ("gradle",), frozenset({"java"})),
    # --- php --------------------------------------------------------
    ("laravel", ("artisan serve", "laravel"), frozenset({"php"})),
    # --- deno/bun ---------------------------------------------------
    ("deno run", ("deno run", "deno task"), frozenset({"deno"})),
    ("bun run", ("bun run", "bun dev"), frozenset({"bun"})),
]

# Substrings in cmdline that make us skip a process entirely (usually
# means we'd be listing ourselves — the `cool` CLI).
IGNORE_PATTERNS: tuple[str, ...] = (
    "cooldown.cli",
    "/.venv/bin/cool",
    "/bin/cool ",
    "/bin/cool\t",
)


@dataclass
class DevProc:
    pid: int
    ppid: int
    lang: str
    framework: str | None
    name: str
    cmdline: str
    rss: int
    cpu_percent: float
    age: float
    cwd: str | None
    project: Project | None
    launcher: Launcher
    is_orphan: bool
    user: str
    idle_seconds: float | None = field(default=None)


def _classify_lang(name: str, cmdline: str) -> str | None:
    hay = f" {name.lower()} {cmdline.lower()} "
    for lang, needles in LANG_PATTERNS:
        for n in needles:
            if n in hay:
                return lang
    return None


def _classify_framework(lang: str, cmdline: str) -> str | None:
    hay = cmdline.lower()
    for label, needles, allowed in FRAMEWORK_PATTERNS:
        if lang not in allowed:
            continue
        for n in needles:
            if n.lower() in hay:
                return label
    return None


def _is_self(name: str, cmdline: str) -> bool:
    hay = cmdline
    if not hay:
        return False
    for needle in IGNORE_PATTERNS:
        if needle in hay:
            return True
    # Defensive: argv0 basename is literally "cool".
    first = hay.split(" ", 1)[0]
    return first.endswith("/cool") or first == "cool"


def collect(sample_interval: float = 0.2) -> list[DevProc]:
    """Return a sorted (by -rss) list of DevProc snapshots.

    Two passes around a ``sample_interval`` sleep so psutil can compute a
    real CPU percentage (first call primes, second call measures).
    """
    # --- Pass 1: match candidates & prime CPU accounting ----------------
    candidates: list[tuple[psutil.Process, str]] = []
    for p in psutil.process_iter(["pid", "name", "cmdline"]):
        try:
            name = p.info["name"] or ""
            cmd = " ".join(p.info["cmdline"] or [])
            if _is_self(name, cmd):
                continue
            lang = _classify_lang(name, cmd)
            if lang is None:
                continue
            candidates.append((p, lang))
            p.cpu_percent(None)  # prime
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue

    time.sleep(sample_interval)

    # --- Pass 2: read CPU/RSS/ppid/etc + enrich -------------------------
    out: list[DevProc] = []
    now = time.time()
    ncpu = psutil.cpu_count(logical=True) or 1
    for p, lang in candidates:
        try:
            with p.oneshot():
                try:
                    cpu = p.cpu_percent(None) / ncpu
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    cpu = 0.0
                try:
                    rss = p.memory_info().rss
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    rss = 0
                try:
                    ppid = p.ppid()
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    ppid = 0
                try:
                    username = p.username()
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    username = ""
                try:
                    name = p.name()
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    name = ""
                try:
                    cmd = " ".join(p.cmdline())
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    cmd = name
                try:
                    ct = p.create_time()
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    ct = now
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue

        if _is_self(name, cmd):
            continue

        framework = _classify_framework(lang, cmd)
        cwd = project_mod.get_cwd(p.pid)
        proj = project_mod.find_root(cwd) if cwd else None
        launcher = ancestry_mod.find_launcher(p.pid)
        is_orphan = ppid == 1 and launcher.kind == "launchd"

        out.append(
            DevProc(
                pid=p.pid,
                ppid=ppid,
                lang=lang,
                framework=framework,
                name=name,
                cmdline=cmd,
                rss=rss,
                cpu_percent=cpu,
                age=max(0.0, now - ct),
                cwd=cwd,
                project=proj,
                launcher=launcher,
                is_orphan=is_orphan,
                user=username,
            )
        )

    out.sort(key=lambda d: (-d.rss, d.pid))
    return out


def enrich_idle(devs: list[DevProc]) -> None:
    """Populate ``DevProc.idle_seconds`` using the same heuristic that
    :mod:`cooldown.collectors.procs` uses (tty atime/mtime fallback).

    Duplicated deliberately so that this module can evolve independently
    of the AI-CLI specific ``procs`` collector.
    """
    now = time.time()
    for d in devs:
        candidates: list[float] = []
        # No tty info on DevProc — rely on cwd mtime as a weak signal and
        # the cpu/age heuristic for the rest.
        if d.cwd:
            try:
                st = os.stat(d.cwd)
                candidates.append(now - st.st_atime)
                candidates.append(now - st.st_mtime)
            except OSError:
                pass
        if not candidates:
            if d.cpu_percent < 1.0:
                candidates.append(min(d.age, 600.0))
            else:
                candidates.append(0.0)
        d.idle_seconds = min(candidates) if candidates else None


def _group_key(dev: DevProc, by: str) -> str:
    if by == "project":
        return dev.project.name if dev.project else "(cwd unknown)"
    if by == "lang":
        return dev.lang
    if by == "launcher":
        return dev.launcher.label or dev.launcher.kind
    if by == "framework":
        return dev.framework or "(none)"
    raise ValueError(f"unknown group key: {by!r}")


def group_by(devs: list[DevProc], by: str) -> dict[str, list[DevProc]]:
    """Group `devs` by the given dimension.

    Groups are sorted by total RSS desc; items inside each group by -rss.
    """
    groups: dict[str, list[DevProc]] = {}
    for d in devs:
        groups.setdefault(_group_key(d, by), []).append(d)
    for v in groups.values():
        v.sort(key=lambda d: (-d.rss, d.pid))
    return dict(
        sorted(
            groups.items(),
            key=lambda kv: (-sum(d.rss for d in kv[1]), kv[0]),
        )
    )


def stale(devs: list[DevProc], *, project_age_days: int = 7) -> list[DevProc]:
    """Return the subset of `devs` that look like forgotten leftovers.

    A dev process is "stale" when:

    - it is orphaned (ppid=1 attached to launchd) OR its project root's
      mtime is older than ``project_age_days``, AND
    - its cpu_percent < 0.5%, AND
    - its idle_seconds (when known) is ≥ 1800 s (30 min).
    """
    cutoff = time.time() - project_age_days * 86400.0
    out: list[DevProc] = []
    for d in devs:
        aged = d.is_orphan
        if not aged and d.project is not None:
            try:
                mt = Path(d.project.root).stat().st_mtime
            except OSError:
                mt = None
            if mt is not None and mt < cutoff:
                aged = True
        if not aged:
            continue
        if d.cpu_percent >= 0.5:
            continue
        if d.idle_seconds is not None and d.idle_seconds < 1800:
            continue
        out.append(d)
    return out

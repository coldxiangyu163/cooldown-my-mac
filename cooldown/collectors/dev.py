"""Dev-stack process inventory: node / python / ruby / go / rust / java /
php / deno / bun / dotnet processes enriched with project + launcher +
framework attribution.

This is the engine behind ``cool dev``. See :mod:`cooldown.ui.dev` for
the presentation layer.
"""
from __future__ import annotations

import os
import re
import time
from dataclasses import dataclass, field
from pathlib import Path

import psutil

from ..util import PROC_ERRORS
from . import ancestry as ancestry_mod
from . import project as project_mod
from .ancestry import Launcher
from .project import Project

# ---------------------------------------------------------------------------
# Language patterns.
#
# We split the old single-list into two groups so we can match them with
# *different strictness*:
#
# - ``BARE_LANG_NAMES`` — short, collision-prone tokens like ``node`` or
#   ``bun``. Previously matched as raw substrings, which mis-classified
#   Electron apps (``--bundle-id=...`` → ``bun``) and native macOS loadable
#   bundles (``Creative Cloud Content Manager.node`` → ``node``). Now these
#   must match the process *name* exactly OR appear as argv[0]'s basename
#   OR show up as a whole word token in cmdline.
#
# - ``TOOL_NEEDLES`` — longer, project-specific tokens like ``uvicorn`` or
#   ``next-server``. Substring match in cmdline is fine because these are
#   unique enough that accidental collisions are rare.
#
# Order inside each group doesn't matter thanks to the strictness rules,
# but we still keep node-ish entries first to preserve test ergonomics.
# ---------------------------------------------------------------------------

BARE_LANG_NAMES: dict[str, tuple[str, ...]] = {
    "node":   ("node", "nodejs"),
    "deno":   ("deno",),
    "bun":    ("bun",),
    "python": ("python", "python3", "pypy", "pypy3"),
    "ruby":   ("ruby",),
    "go":     ("go",),
    "rust":   ("rustc",),
    "java":   ("java",),
    "php":    ("php", "php-fpm"),
    "dotnet": ("dotnet", "mono"),
}

TOOL_NEEDLES: dict[str, tuple[str, ...]] = {
    "node":   ("npm ", "pnpm ", "yarn ", "npx ", "corepack"),
    "python": ("uvicorn", "gunicorn", "celery", "jupyter", "streamlit", "pytest"),
    "ruby":   ("rails ", "rake ", "bundle exec", "puma", "sidekiq"),
    "go":     ("go run", "gopls"),
    "rust":   ("cargo ", "rust-analyzer"),
    "java":   ("gradle", "mvn ", "kotlin"),
    "php":    ("artisan",),
}

# Process names that represent loadable files (native add-ons, scripts)
# rather than live language runtimes. Never classify these.
REJECT_NAME_SUFFIXES: tuple[str, ...] = (
    ".node", ".py", ".pyc", ".pyo", ".rb", ".rbc", ".sh",
)

# Cached word-boundary regex for a single token.
_WORD = re.compile(r"[A-Za-z0-9_]+")

def _first_argv0_basename(cmd: str) -> str:
    head = cmd.split(" ", 1)[0] if cmd else ""
    return head.rsplit("/", 1)[-1]

def _is_whole_word(hay: str, needle: str) -> bool:
    """True iff ``needle`` appears as a whole word in ``hay``.

    "bun" in "bundle" -> False.  "bun" in "/bin/bun --args" -> True.
    """
    return any(match.group(0) == needle for match in _WORD.finditer(hay))

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
    name_l = name.lower()
    # Loadable-file names like "Creative Cloud Content Manager.node" are
    # not live runtimes — drop them early.
    for suffix in REJECT_NAME_SUFFIXES:
        if name_l.endswith(suffix):
            return None

    cmd_l = cmdline.lower()
    argv0_base = _first_argv0_basename(cmd_l)

    # Pass 1: bare language tokens. Must match name exactly, be the
    # basename of argv[0], or appear as a whole word in cmdline. No more
    # "--bundle-id=..." false positives.
    for lang, names in BARE_LANG_NAMES.items():
        for needle in names:
            if name_l == needle or argv0_base == needle:
                return lang
            if _is_whole_word(cmd_l, needle):
                return lang

    # Pass 2: unique tool needles. Substring in cmdline is fine here.
    for lang, needles in TOOL_NEEDLES.items():
        for needle in needles:
            if needle in cmd_l:
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


_APP_BUNDLE_RE = re.compile(r"/([^/]+?)\.app/")

# ---------------------------------------------------------------------------
# Additional attribution sources for processes that would otherwise land in
# "(cwd unknown)". Applied in order after find_root + _synthesize_app_project
# so on-disk markers always win.
# ---------------------------------------------------------------------------

# npx / npm global cache: /Users/.../.npm/_npx/<hash>/node_modules/<pkg>/...
_NPX_CACHE_RE = re.compile(r"/\.npm/_npx/[0-9a-f]+/node_modules/((?:@[^/\s]+/)?[^/\s]+)")
# Fallback for live shells — "npm exec <pkg>" or "npx <pkg>".
_NPM_EXEC_RE = re.compile(r"(?:^|\s)(?:npx|npm\s+exec)(?:\s+-\S+)*\s+((?:@[^/\s]+/)?[^\s@]+)")

# VS Code extensions:
# /Users/<u>/.vscode/extensions/<publisher>.<name>-<version>[-arch]/...
_VSCODE_EXT_RE = re.compile(
    r"/\.vscode(?:-[a-z]+)?/extensions/([^./]+)\.([^/\s-]+(?:-[^/\s-]+)*?)-\d[\w.]*"
)

# Known "project container" anchors inside a user's filesystem layout. If cwd
# walks through one of these, the *next* segment is the project name even
# when the directory has already been deleted (stale cwd of long-running
# processes).
_PROJECT_ANCHORS: tuple[tuple[str, ...], ...] = (
    ("personal", "project"),
    ("personal", "projects"),
    ("work",),
    ("code",),
    ("src",),
    ("repos",),
    ("workspace",),
    ("projects",),
    ("dev",),
    ("Documents", "GitHub"),
    ("go", "src"),
)

# Monorepo subdirectories — when cwd is `<repo>/apps/web`, the bucket is the
# <repo>, not "web".
_MONOREPO_SUBDIRS = frozenset({
    "apps", "app", "packages", "services", "libs", "lib", "modules",
    "frontend", "backend", "web", "server", "client",
})


def _walk_past_monorepo(proj: Project) -> Project:
    """If a project root sits inside a monorepo layer (``apps/<x>``,
    ``packages/<x>``, ...), walk up past that layer to find the workspace
    root so ``my-repo/apps/web`` and ``my-repo/apps/api`` collapse into
    ``my-repo`` instead of each becoming its own ``web`` / ``api`` bucket.
    """
    root = proj.root
    try:
        parent = root.parent
        grand = parent.parent
    except (AttributeError, OSError):
        return proj
    if parent.name not in _MONOREPO_SUBDIRS:
        return proj
    if grand == parent:
        return proj
    outer = project_mod.find_root(grand, max_depth=1)
    if outer is not None:
        return outer
    # Even without markers, synthesise the workspace bucket from the path.
    return Project(root=grand, name=grand.name, markers=["<monorepo>"])


def _synthesize_npx_project(cmdline: str) -> Project | None:
    """Attribute npx-cache / `npm exec <pkg>` to ``(npx: <pkg>)``."""
    if not cmdline:
        return None
    m = _NPX_CACHE_RE.search(cmdline)
    if m:
        pkg = m.group(1)
        return Project(
            root=Path("/"), name=f"(npx: {pkg})", markers=["<npx>"]
        )
    m = _NPM_EXEC_RE.search(cmdline)
    if m:
        pkg = m.group(1)
        return Project(
            root=Path("/"), name=f"(npx: {pkg})", markers=["<npx>"]
        )
    return None


def _synthesize_vscode_ext_project(cmdline: str, cwd: str | None) -> Project | None:
    """Attribute VS Code / Cursor extension child procs to ``(vscode: <ext>)``."""
    for source in (cmdline or "", cwd or ""):
        if not source:
            continue
        m = _VSCODE_EXT_RE.search(source)
        if m:
            ext_name = m.group(2)
            return Project(
                root=Path("/"), name=f"(vscode: {ext_name})", markers=["<ext>"]
            )
    return None


def _synthesize_cwd_project(cwd: str | None) -> Project | None:
    """Parse a cwd *string* into a project bucket even when the directory
    no longer exists on disk.

    Long-running dev processes frequently outlive ``git clone`` paths —
    the user deletes / moves the tree, the kernel keeps the inode, and
    the cwd is now a ghost. We still know the original path so we can
    reconstruct the project name by pattern-matching against common
    "project container" layouts under ``$HOME``.

    Also folds known monorepo subdirs (``apps/web`` etc.) up so
    ``~/code/my-repo/apps/web`` and ``~/code/my-repo/packages/ui`` both
    attribute to ``my-repo`` rather than ``web`` / ``ui``.
    """
    if not cwd:
        return None
    # Tolerate Path(str) failing on non-UTF-8 or gibberish.
    try:
        p = Path(cwd)
    except (OSError, ValueError):
        return None
    if str(p) in ("/", ".", ""):
        return None
    parts = p.parts

    # 1. Try matching each known "project container" anchor relative to $HOME.
    # macOS user homes live under /Users/<name>/; Linux under /home/<name>/.
    # Accept both the current process's $HOME *and* the generic pattern so
    # foreign-owned procs (and unit tests) resolve correctly.
    home = Path.home()
    try:
        home_parts = home.parts
    except AttributeError:
        home_parts = ()
    home_idx: int | None = None
    # Exact current-user $HOME match first.
    if home_parts:
        for i in range(len(parts) - len(home_parts) + 1):
            if tuple(parts[i:i + len(home_parts)]) == home_parts:
                home_idx = i + len(home_parts)
                break
    # Fall back to generic /Users/<x>/ or /home/<x>/ anchor.
    if home_idx is None:
        for i in range(len(parts) - 1):
            if parts[i] in ("Users", "home") and i + 1 < len(parts):
                home_idx = i + 2
                break
    if home_idx is not None and home_idx < len(parts):
        rest = parts[home_idx:]
        for anchor in _PROJECT_ANCHORS:
            if len(rest) > len(anchor) and tuple(rest[:len(anchor)]) == anchor:
                name = rest[len(anchor)]
                root_parts = parts[:home_idx + len(anchor) + 1]
                return Project(
                    root=Path(*root_parts),
                    name=name,
                    markers=["<cwd>"],
                )

    # 2. Fold monorepo subdirs (apps/web, packages/ui, ...) up one level.
    # Only applies when the *containing* segment is a known subdir.
    for i in range(len(parts) - 1, 0, -1):
        if parts[i] in _MONOREPO_SUBDIRS and i >= 1 and i + 1 < len(parts):
            root_parts = parts[: i]
            if root_parts and root_parts[-1] not in ("", "/"):
                return Project(
                    root=Path(*root_parts),
                    name=root_parts[-1],
                    markers=["<monorepo>"],
                )

    # 3. Hidden tool dirs under $HOME: ~/.mcporter, ~/.nanobot/workspace
    if home_idx is not None and home_idx < len(parts):
        tail = parts[home_idx]
        if tail.startswith("."):
            tool = tail.lstrip(".")
            return Project(
                root=Path(*parts[:home_idx + 1]),
                name=f"(tool: {tool})",
                markers=["<hidden>"],
            )

    # 4. Absolute last resort: if the cwd has at least one real segment
    # and is under $HOME, use the first subdir name.
    if home_idx is not None and home_idx < len(parts):
        return Project(
            root=Path(*parts[:home_idx + 1]),
            name=parts[home_idx],
            markers=["<cwd>"],
        )
    return None


def _synthesize_cmdline_project(cmdline: str) -> Project | None:
    """Last-resort attribution from cmdline flags. Covers ``pnpm --dir
    <path>`` and similar tool invocations that point at a project root
    even when the caller's cwd is ``/``.
    """
    if not cmdline:
        return None
    for flag in ("--dir ", "--cwd ", "--prefix "):
        idx = cmdline.find(flag)
        if idx == -1:
            continue
        tail = cmdline[idx + len(flag):].strip()
        # Support quoted or whitespace-delimited paths.
        if tail.startswith(("'", '"')):
            quote = tail[0]
            end = tail.find(quote, 1)
            if end == -1:
                continue
            path = tail[1:end]
        else:
            path = tail.split(" ", 1)[0]
        if path:
            proj = _synthesize_cwd_project(path)
            if proj is not None:
                return proj
    return None


def _synthesize_app_project(name: str, cmdline: str, cwd: str | None) -> Project | None:
    """Best-effort attribution for processes that have no project marker
    on disk but are clearly owned by a macOS application.

    Catches the 90% case of "(cwd unknown)" noise in ``Top Projects by
    RSS``: Electron helpers (VS Code / Obsidian / WeChatAppEx / Notion
    / Slack), native app runtimes shelling out to Node or Python, and
    anything whose argv path walks through an ``.app`` bundle.

    Returns a synthetic ``Project`` labelled ``(app: <AppName>)`` so the
    UI can distinguish it from real on-disk projects, while still
    offering a *one-row-per-app* grouping instead of 20 scattered
    helpers under ``(cwd unknown)``.
    """
    for source in (cmdline or "", cwd or ""):
        if not source:
            continue
        m = _APP_BUNDLE_RE.search(source)
        if m:
            app_name = m.group(1).strip()
            if app_name:
                bundle_root = Path(source.split(".app/", 1)[0] + ".app")
                return Project(
                    root=bundle_root, name=f"(app: {app_name})", markers=["<bundle>"]
                )
    # Fallback: the executable name itself says "<App> Helper (...)".
    if " Helper" in name:
        app = name.split(" Helper", 1)[0].strip()
        if app:
            return Project(
                root=Path(cwd or "/"), name=f"(app: {app})", markers=["<helper>"]
            )
    return None


def _bucket_orphan_project(cwd: str | None, is_orphan: bool) -> Project | None:
    """Collapse the remaining stragglers (cwd=/ or cwd=$HOME orphan
    processes) into a single ``(orphan)`` bucket rather than leaving them
    as anonymous ``(cwd unknown)`` lines. Only applied when the process
    is a launchd-orphan *and* we have no better attribution.
    """
    if not is_orphan:
        return None
    if cwd in (None, "", "/", str(Path.home())):
        return Project(
            root=Path(cwd or "/"), name="(orphan)", markers=["<orphan>"]
        )
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
    # NB: do not pre-fetch cmdline via process_iter attrs — see comment
    # in cooldown/util.py::PROC_ERRORS for why (macOS EPERM/SystemError).
    candidates: list[tuple[psutil.Process, str]] = []
    for p in psutil.process_iter(["pid", "name"]):
        try:
            name = p.info["name"] or ""
            try:
                cmd = " ".join(p.cmdline() or [])
            except PROC_ERRORS:
                cmd = ""
            if _is_self(name, cmd):
                continue
            lang = _classify_lang(name, cmd)
            if lang is None:
                continue
            candidates.append((p, lang))
            p.cpu_percent(None)  # prime
        except PROC_ERRORS:
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
                except PROC_ERRORS:
                    cpu = 0.0
                try:
                    rss = p.memory_info().rss
                except PROC_ERRORS:
                    rss = 0
                try:
                    ppid = p.ppid()
                except PROC_ERRORS:
                    ppid = 0
                try:
                    username = p.username()
                except PROC_ERRORS:
                    username = ""
                try:
                    name = p.name()
                except PROC_ERRORS:
                    name = ""
                try:
                    cmd = " ".join(p.cmdline())
                except PROC_ERRORS:
                    cmd = name
                try:
                    ct = p.create_time()
                except PROC_ERRORS:
                    ct = now
        except PROC_ERRORS:
            continue

        if _is_self(name, cmd):
            continue

        framework = _classify_framework(lang, cmd)
        cwd = project_mod.get_cwd(p.pid)
        proj = project_mod.find_root(cwd) if cwd else None
        if proj is not None:
            proj = _walk_past_monorepo(proj)
        launcher = ancestry_mod.find_launcher(p.pid)
        is_orphan = ppid == 1 and launcher.kind == "launchd"
        # If no real on-disk project, try progressively weaker fallbacks so
        # that every dev process gets *some* attribution and the
        # "(cwd unknown)" bucket stays empty.
        if proj is None:
            proj = _synthesize_app_project(name, cmd, cwd)
        if proj is None:
            proj = _synthesize_npx_project(cmd)
        if proj is None:
            proj = _synthesize_vscode_ext_project(cmd, cwd)
        if proj is None:
            proj = _synthesize_cmdline_project(cmd)
        if proj is None:
            proj = _synthesize_cwd_project(cwd)
        if proj is None:
            proj = _bucket_orphan_project(cwd, is_orphan)

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
        if dev.project is not None:
            return dev.project.name
        # Ultimate fallback — we couldn't find a disk marker, an .app
        # bundle, an npx cache, a VS Code extension, a parseable cwd, or
        # an orphan anchor. Bucket as "(background)" keyed by the first
        # cmdline token so related procs still cluster meaningfully.
        head = dev.cmdline.split(" ", 1)[0] if dev.cmdline else dev.name
        head = head.rsplit("/", 1)[-1] or dev.name or "proc"
        return f"(background: {head})"
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

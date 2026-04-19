"""AI CLI process inventory, grouping, and idle detection."""
from __future__ import annotations

import os
import time
from dataclasses import dataclass, field

import psutil

from ..util import PROC_ERRORS

# Patterns that identify AI CLIs / terminal multiplexers / bot gateways we
# care about. Order matters: the first match wins.
#
# Each entry is ``(kind, needles)`` and a process is classified under
# ``kind`` when ANY needle is a substring of the padded haystack
# ``f" {name} {cmdline} "`` (lowercased). Padding with spaces on both
# sides lets us use `" gemini "` style needles that behave like
# whitespace-delimited word boundaries and still match bare invocations
# such as ``gemini --help`` whose cmdline has no trailing space.
#
# Keep more specific kinds (e.g. ``cursor-agent``) listed BEFORE more
# generic ones so they win the first-match race.
KIND_PATTERNS: list[tuple[str, tuple[str, ...]]] = [
    # --- Factory-first AI CLIs ---------------------------------------
    ("droid", ("droid",)),
    ("codex", ("codex",)),
    ("claude", ("claude",)),
    ("opencode", ("opencode",)),
    ("nanobot", ("nanobot",)),
    ("hermes", ("hermes",)),
    # --- Other popular AI CLIs / coding agents -----------------------
    # Prefer distinctive package paths (``@org/pkg``) and path-anchored
    # needles (``/bin``, ``/gemini``) over bare words, because the bare
    # word variants are already covered via word-boundary ("` gemini `")
    # matching on the padded haystack.
    ("gemini", ("@google/gemini", "gemini-cli", "/gemini", " gemini ")),
    ("aider", ("aider-chat", "/aider", " aider ")),
    ("cursor-agent", ("cursor-agent",)),
    ("copilot", (
        "github-copilot",
        "github.copilot",  # VS Code / Cursor extension id (e.g. github.copilot-1.0.0)
        "@github/copilot",
        "gh-copilot",
        "copilot-cli",
        "copilot-language-server",
        ".copilot/",
        "/copilot",
        " copilot ",
    )),
    ("windsurf", ("windsurf",)),
    ("qwen", ("@qwen-code/", "qwen-code", "qwen-coder", " qwen ")),
    ("kimi", ("@moonshot/", "kimi-cli", "kimi-code", "kimi-coder")),
    ("goose", ("block-goose", "goose-cli", "/goose", " goose ")),
    ("aichat", ("aichat",)),
    ("continue", ("@continuedev/", "continuedev", ".continue/")),
    ("amp", ("@sourcegraph/amp", "sourcegraph-amp")),
    ("crush", ("@charm/crush", "charmbracelet/crush")),
    # --- Multiplexers ------------------------------------------------
    ("cmux", ("cmux",)),
    ("tmux", ("tmux",)),
    ("zellij", ("zellij",)),
]

AI_KINDS = {
    "droid",
    "codex",
    "claude",
    "opencode",
    "nanobot",
    "hermes",
    "gemini",
    "aider",
    "cursor-agent",
    "copilot",
    "windsurf",
    "qwen",
    "kimi",
    "goose",
    "aichat",
    "continue",
    "amp",
    "crush",
}
MUX_KINDS = {"tmux", "cmux", "zellij"}


@dataclass
class ProcInfo:
    pid: int
    ppid: int
    kind: str
    name: str
    cmdline: str
    rss: int
    cpu_percent: float
    create_time: float
    age: float
    tty: str | None
    user: str

    # Set later by enrich_idle()
    idle_seconds: float | None = field(default=None)


def _classify(name: str, cmdline: str) -> str | None:
    # Pad with spaces so word-boundary style needles like `" gemini "`
    # also match `name`-only cases where `cmdline` is empty or the binary
    # appears at the edge of the haystack.
    hay = f" {name} {cmdline} ".lower()
    for kind, needles in KIND_PATTERNS:
        for needle in needles:
            if needle in hay:
                return kind
    return None


def collect(sample_interval: float = 0.25) -> list[ProcInfo]:
    """Return a list of processes classified into our known kinds.

    We sample CPU percent across a short interval to avoid the first-call
    psutil returning 0.0 for everything.
    """
    candidates: list[tuple[psutil.Process, str]] = []
    # NOTE: we intentionally *do not* pre-fetch "cmdline" via process_iter
    # attrs, because on macOS some sysctl calls raise SystemError which
    # would propagate out of the whole iterator. Instead we read cmdline
    # inside each per-process try block, which is guarded by PROC_ERRORS.
    for p in psutil.process_iter(["pid", "name"]):
        try:
            name = p.info["name"] or ""
            try:
                cmd = " ".join(p.cmdline() or [])
            except PROC_ERRORS:
                cmd = ""
            kind = _classify(name, cmd)
            if kind is None:
                continue
            candidates.append((p, kind))
            p.cpu_percent(None)  # prime CPU accounting
        except PROC_ERRORS:
            continue

    time.sleep(sample_interval)

    results: list[ProcInfo] = []
    now = time.time()
    ncpu = psutil.cpu_count(logical=True) or 1
    for p, kind in candidates:
        try:
            with p.oneshot():
                cpu = p.cpu_percent(None) / ncpu  # normalize to single-core %
                mem = p.memory_info().rss
                ct = p.create_time()
                ppid = p.ppid()
                username = p.username()
                name = p.name()
                try:
                    cmd = " ".join(p.cmdline())
                except PROC_ERRORS:
                    cmd = name
                try:
                    tty = p.terminal()
                except (*PROC_ERRORS, AttributeError):
                    tty = None
            results.append(
                ProcInfo(
                    pid=p.pid,
                    ppid=ppid,
                    kind=kind,
                    name=name,
                    cmdline=cmd,
                    rss=mem,
                    cpu_percent=cpu,
                    create_time=ct,
                    age=max(0.0, now - ct),
                    tty=tty,
                    user=username,
                )
            )
        except PROC_ERRORS:
            continue
    return results


def enrich_idle(procs: list[ProcInfo]) -> None:
    """Populate `idle_seconds` using the most recent mtime/atime of the
    controlling tty when available. This is a best-effort heuristic because
    macOS does not expose per-process "last activity" directly.

    A low CPU percent over our sample AND an old tty atime implies idle.
    """
    now = time.time()
    for p in procs:
        candidates: list[float] = []
        if p.tty:
            tty_path = p.tty if p.tty.startswith("/") else f"/dev/{p.tty}"
            try:
                st = os.stat(tty_path)
                candidates.append(now - st.st_atime)
                candidates.append(now - st.st_mtime)
            except OSError:
                pass
        # Fallback: if CPU is quiet, use a fraction of the process age so
        # newly spawned processes do not look idle for hours just because we
        # have no tty reading.
        if not candidates:
            if p.cpu_percent < 1.0:
                candidates.append(min(p.age, 600.0))  # cap at 10min
            else:
                candidates.append(0.0)
        p.idle_seconds = min(candidates) if candidates else None


def group_by_kind(procs: list[ProcInfo]) -> dict[str, list[ProcInfo]]:
    out: dict[str, list[ProcInfo]] = {}
    for p in procs:
        out.setdefault(p.kind, []).append(p)
    for v in out.values():
        v.sort(key=lambda x: (-x.rss, x.pid))
    return dict(sorted(out.items(), key=lambda kv: (-sum(p.rss for p in kv[1]), kv[0])))

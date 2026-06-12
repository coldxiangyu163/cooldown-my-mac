"""Kill / terminate processes with a dry-run mode and op-log trail."""
from __future__ import annotations

import os
import signal
from dataclasses import dataclass

import psutil

from ..collectors.leftovers import is_chromium
from ..collectors.procs import ProcInfo
from ..safety.oplog import record

# Automation browsers spawn a helper fleet (renderer / gpu / utility / zygote
# / crashpad). Killing only the root can leave the helpers respawning or
# lingering, so for this kind we expand the target to its whole live subtree.
_SUBTREE_KIND = "automation-browser"


@dataclass
class KillOutcome:
    pid: int
    kind: str
    command: str
    ok: bool
    message: str


def _self_pid_chain() -> set[int]:
    """Return pids we must never kill (ourselves and our ancestors).

    Prevents a user running `cool reap` inside a tmux/droid session from
    accidentally terminating the very shell executing the command.
    """
    chain: set[int] = set()
    try:
        p = psutil.Process(os.getpid())
        while p is not None:
            chain.add(p.pid)
            try:
                p = p.parent()
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                break
            if p is None or p.pid == 0:
                break
    except psutil.Error:
        chain.add(os.getpid())
    return chain


def _descendants(pid: int) -> list[tuple[int, str, str, float]]:
    """Live descendants of `pid` as ``(pid, name, exe, create_time)``, captured
    at enumeration so the killer can vet each child and validate it against PID
    reuse before signaling. Best-effort and read-only; missing/inaccessible
    processes are skipped."""
    try:
        kids = psutil.Process(pid).children(recursive=True)
    except psutil.Error:
        return []
    out: list[tuple[int, str, str, float]] = []
    for c in kids:
        try:
            with c.oneshot():
                name = c.name()
                try:
                    exe = c.exe() or ""
                except (psutil.Error, OSError):
                    exe = ""
                out.append((c.pid, name, exe, c.create_time()))
        except psutil.Error:
            continue
    return out


def _expand_targets(targets: list[ProcInfo], protected: set[int]) -> list[ProcInfo]:
    """Expand automation-browser targets to include their live subtree so a
    Chrome helper fleet is torn down with the root. Plain AI-CLI / mux targets
    keep single-process semantics. Deduped by pid; protected pids (self /
    ancestors) are never added.

    Defense in depth: the killer trusts the collector's classification of the
    *root*, but re-checks each descendant is itself chromium so a process
    reparented under the root is never swept into the kill set. Each child
    carries its real name / create_time for honest oplog + PID-reuse validation.
    """
    seen = {t.pid for t in targets}
    expanded = list(targets)
    for t in targets:
        if t.kind != _SUBTREE_KIND:
            continue
        for child_pid, name, exe, create_time in _descendants(t.pid):
            if child_pid in seen or child_pid in protected:
                continue
            if not is_chromium(name, exe):
                continue
            seen.add(child_pid)
            expanded.append(
                ProcInfo(
                    pid=child_pid,
                    ppid=t.pid,
                    kind=t.kind,
                    name=name,
                    cmdline=f"(subtree of pid {t.pid}) {name}",
                    rss=0,
                    cpu_percent=0.0,
                    create_time=create_time,
                    age=t.age,
                    tty=None,
                    user=t.user,
                    idle_seconds=t.idle_seconds,
                )
            )
    return expanded


def terminate(
    targets: list[ProcInfo],
    *,
    dry_run: bool = False,
    force: bool = False,
    timeout: float = 3.0,
) -> list[KillOutcome]:
    """Terminate the given processes. Uses SIGTERM, escalates to SIGKILL
    when `force=True` or when the process does not exit within `timeout`.

    Automation-browser targets are expanded to their full live subtree so the
    Chrome helper fleet is reaped with the root (honored in dry-run too).
    """
    outcomes: list[KillOutcome] = []
    protected = _self_pid_chain()
    targets = _expand_targets(targets, protected)

    for info in targets:
        if info.pid in protected:
            outcomes.append(
                KillOutcome(info.pid, info.kind, info.cmdline, False, "protected (self/ancestor)")
            )
            continue

        if dry_run:
            outcomes.append(
                KillOutcome(info.pid, info.kind, info.cmdline, True, "dry-run: would terminate")
            )
            record(
                "reap.dry-run",
                pid=info.pid,
                kind=info.kind,
                cmd=info.cmdline[:200],
                rss=info.rss,
                idle=info.idle_seconds,
            )
            continue

        try:
            p = psutil.Process(info.pid)
            # PID-reuse guard: if the live process at this pid is not the one we
            # classified (create_time drifted), the pid was recycled — refuse to
            # signal it. Matters most on the autonomous daemon path and when
            # killing a large subtree sequentially. create_time==0.0 means the
            # caller carried no identity (e.g. legacy callers/tests) -> skip check.
            if info.create_time and abs(p.create_time() - info.create_time) > 1.0:
                outcomes.append(
                    KillOutcome(info.pid, info.kind, info.cmdline, False, "skipped: pid recycled")
                )
                record("reap.skip", pid=info.pid, kind=info.kind, reason="pid-recycled")
                continue
            sig = signal.SIGKILL if force else signal.SIGTERM
            sent_signal = sig.name
            p.send_signal(sig)
            try:
                p.wait(timeout=timeout)
                outcomes.append(
                    KillOutcome(info.pid, info.kind, info.cmdline, True, f"sent {sig.name}")
                )
            except psutil.TimeoutExpired:
                # SIGTERM ignored — escalate to SIGKILL. If the process dies
                # from the initial signal in the window before kill(), record it
                # honestly (it WAS our kill) instead of letting the NoSuchProcess
                # bubble out and be misreported as "already gone".
                try:
                    p.kill()
                    p.wait(timeout=timeout)
                    sent_signal = "SIGKILL"
                    outcomes.append(
                        KillOutcome(info.pid, info.kind, info.cmdline, True, "escalated to SIGKILL")
                    )
                except psutil.NoSuchProcess:
                    outcomes.append(
                        KillOutcome(
                            info.pid, info.kind, info.cmdline, True, f"exited after {sig.name}"
                        )
                    )
            record(
                "reap.kill",
                pid=info.pid,
                kind=info.kind,
                cmd=info.cmdline[:200],
                rss=info.rss,
                idle=info.idle_seconds,
                signal=sent_signal,
            )
        except psutil.NoSuchProcess:
            outcomes.append(KillOutcome(info.pid, info.kind, info.cmdline, True, "already gone"))
        except psutil.AccessDenied as e:
            outcomes.append(
                KillOutcome(info.pid, info.kind, info.cmdline, False, f"denied: {e}")
            )
        except Exception as e:  # noqa: BLE001
            outcomes.append(KillOutcome(info.pid, info.kind, info.cmdline, False, str(e)))
    return outcomes

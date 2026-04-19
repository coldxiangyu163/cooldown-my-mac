"""Kill / terminate processes with a dry-run mode and op-log trail."""
from __future__ import annotations

import os
import signal
from dataclasses import dataclass

import psutil

from ..collectors.procs import ProcInfo
from ..safety.oplog import record


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


def terminate(
    targets: list[ProcInfo],
    *,
    dry_run: bool = False,
    force: bool = False,
    timeout: float = 3.0,
) -> list[KillOutcome]:
    """Terminate the given processes. Uses SIGTERM, escalates to SIGKILL
    when `force=True` or when the process does not exit within `timeout`.
    """
    outcomes: list[KillOutcome] = []
    protected = _self_pid_chain()

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
            sig = signal.SIGKILL if force else signal.SIGTERM
            p.send_signal(sig)
            try:
                p.wait(timeout=timeout)
                outcomes.append(
                    KillOutcome(info.pid, info.kind, info.cmdline, True, f"sent {sig.name}")
                )
            except psutil.TimeoutExpired:
                p.kill()
                p.wait(timeout=timeout)
                outcomes.append(
                    KillOutcome(info.pid, info.kind, info.cmdline, True, "escalated to SIGKILL")
                )
            record(
                "reap.kill",
                pid=info.pid,
                kind=info.kind,
                cmd=info.cmdline[:200],
                rss=info.rss,
                idle=info.idle_seconds,
                signal=sig.name if not force else "SIGKILL",
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

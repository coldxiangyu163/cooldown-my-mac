"""Suspend / resume / quit heavy apps with dry-run + oplog trail."""
from __future__ import annotations

import signal
import subprocess
from dataclasses import dataclass

import psutil

from ..collectors.apps import AppInfo
from ..safety.oplog import record
from .reap import _self_pid_chain


@dataclass
class AppActionOutcome:
    kind: str
    pid: int
    action: str
    ok: bool
    message: str


def _process_tree(pid: int) -> list[psutil.Process]:
    """Return [main, *descendants] for the given pid, skipping gone procs."""
    try:
        main = psutil.Process(pid)
    except psutil.NoSuchProcess:
        return []
    try:
        children = main.children(recursive=True)
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        children = []
    return [main, *children]


def _signal_tree(pid: int, sig: signal.Signals) -> tuple[int, int, list[str]]:
    """Send `sig` to every pid in the tree rooted at `pid`.

    Returns (sent, failed, errors).
    """
    protected = _self_pid_chain()
    sent = 0
    failed = 0
    errors: list[str] = []
    for proc in _process_tree(pid):
        if proc.pid in protected:
            failed += 1
            errors.append(f"pid={proc.pid} protected")
            continue
        try:
            proc.send_signal(sig)
            sent += 1
        except psutil.NoSuchProcess:
            # Already gone — benign.
            continue
        except psutil.AccessDenied as e:
            failed += 1
            errors.append(f"pid={proc.pid} denied: {e}")
        except Exception as e:  # noqa: BLE001
            failed += 1
            errors.append(f"pid={proc.pid} {e}")
    return sent, failed, errors


def suspend(app: AppInfo, *, dry_run: bool = False) -> AppActionOutcome:
    if dry_run:
        record("apps.suspend.dry-run", kind=app.kind, pid=app.pid, name=app.display_name)
        return AppActionOutcome(app.kind, app.pid, "suspend", True, "dry-run: would SIGSTOP tree")

    sent, failed, errs = _signal_tree(app.pid, signal.SIGSTOP)
    ok = failed == 0 and sent > 0
    msg = f"SIGSTOP sent to {sent} pid(s)"
    if failed:
        msg += f"; {failed} failed ({'; '.join(errs[:3])})"
    record(
        "apps.suspend",
        kind=app.kind,
        pid=app.pid,
        name=app.display_name,
        sent=sent,
        failed=failed,
        ok=ok,
    )
    return AppActionOutcome(app.kind, app.pid, "suspend", ok, msg)


def resume(app: AppInfo, *, dry_run: bool = False) -> AppActionOutcome:
    if dry_run:
        record("apps.resume.dry-run", kind=app.kind, pid=app.pid, name=app.display_name)
        return AppActionOutcome(app.kind, app.pid, "resume", True, "dry-run: would SIGCONT tree")

    sent, failed, errs = _signal_tree(app.pid, signal.SIGCONT)
    ok = failed == 0 and sent > 0
    msg = f"SIGCONT sent to {sent} pid(s)"
    if failed:
        msg += f"; {failed} failed ({'; '.join(errs[:3])})"
    record(
        "apps.resume",
        kind=app.kind,
        pid=app.pid,
        name=app.display_name,
        sent=sent,
        failed=failed,
        ok=ok,
    )
    return AppActionOutcome(app.kind, app.pid, "resume", ok, msg)


def _osascript_quit(app_name: str, *, timeout: float = 6.0) -> tuple[bool, str]:
    try:
        proc = subprocess.run(
            ["osascript", "-e", f'tell application "{app_name}" to quit'],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as e:
        return False, f"osascript error: {e}"
    if proc.returncode == 0:
        return True, "osascript quit requested"
    return False, (proc.stderr or proc.stdout or f"osascript exited {proc.returncode}").strip()


def quit_app(app: AppInfo, *, dry_run: bool = False, timeout: float = 5.0) -> AppActionOutcome:
    if dry_run:
        record("apps.quit.dry-run", kind=app.kind, pid=app.pid, name=app.display_name)
        return AppActionOutcome(app.kind, app.pid, "quit", True, "dry-run: would quit")

    protected = _self_pid_chain()
    if app.pid in protected:
        record(
            "apps.quit",
            kind=app.kind,
            pid=app.pid,
            name=app.display_name,
            ok=False,
            message="protected",
        )
        return AppActionOutcome(app.kind, app.pid, "quit", False, "protected (self/ancestor)")

    ok, msg = _osascript_quit(app.display_name, timeout=timeout)
    # Wait briefly for the app to exit gracefully; fall back to SIGTERM.
    exited = False
    try:
        p = psutil.Process(app.pid)
        try:
            p.wait(timeout=timeout)
            exited = True
        except psutil.TimeoutExpired:
            exited = False
    except psutil.NoSuchProcess:
        exited = True

    if exited:
        record(
            "apps.quit",
            kind=app.kind,
            pid=app.pid,
            name=app.display_name,
            via="osascript",
            ok=True,
            message=msg[:200],
        )
        return AppActionOutcome(app.kind, app.pid, "quit", True, msg or "quit via osascript")

    # Fallback: SIGTERM to the main pid.
    try:
        psutil.Process(app.pid).send_signal(signal.SIGTERM)
        fallback_msg = f"osascript: {msg}; fallback SIGTERM sent"
        record(
            "apps.quit",
            kind=app.kind,
            pid=app.pid,
            name=app.display_name,
            via="sigterm",
            ok=True,
            message=fallback_msg[:200],
        )
        return AppActionOutcome(app.kind, app.pid, "quit", True, fallback_msg)
    except psutil.NoSuchProcess:
        return AppActionOutcome(app.kind, app.pid, "quit", True, "already gone")
    except Exception as e:  # noqa: BLE001
        record(
            "apps.quit",
            kind=app.kind,
            pid=app.pid,
            name=app.display_name,
            via="error",
            ok=ok,
            message=str(e)[:200],
        )
        return AppActionOutcome(app.kind, app.pid, "quit", False, f"{msg}; fallback failed: {e}")

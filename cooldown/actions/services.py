"""Start / stop local dev services, with dry-run and oplog trail."""
from __future__ import annotations

import shutil
import signal
import subprocess
from dataclasses import dataclass

import psutil

from ..collectors.services import ServiceInfo
from ..safety.oplog import record
from .reap import _self_pid_chain


@dataclass
class ServiceOutcome:
    name: str
    action: str
    ok: bool
    message: str


def _brew_available() -> bool:
    return shutil.which("brew") is not None


def _run_brew(subcmd: str, name: str, timeout: float = 15.0) -> tuple[bool, str]:
    try:
        proc = subprocess.run(
            ["brew", "services", subcmd, name],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as e:
        return False, f"brew error: {e}"
    if proc.returncode == 0:
        out = (proc.stdout or "").strip().splitlines()
        return True, (out[-1] if out else f"brew services {subcmd} {name} ok")
    return False, (proc.stderr or proc.stdout or f"brew exited {proc.returncode}").strip()


def _terminate_pid(pid: int, *, timeout: float = 5.0) -> tuple[bool, str]:
    protected = _self_pid_chain()
    if pid in protected:
        return False, "protected (self/ancestor)"
    try:
        p = psutil.Process(pid)
        p.send_signal(signal.SIGTERM)
        try:
            p.wait(timeout=timeout)
            return True, "sent SIGTERM"
        except psutil.TimeoutExpired:
            p.kill()
            try:
                p.wait(timeout=timeout)
            except psutil.TimeoutExpired:
                return False, "still alive after SIGKILL"
            return True, "escalated to SIGKILL"
    except psutil.NoSuchProcess:
        return True, "already gone"
    except psutil.AccessDenied as e:
        return False, f"denied: {e}"
    except Exception as e:  # noqa: BLE001
        return False, str(e)


def start(svc: ServiceInfo, *, dry_run: bool = False) -> ServiceOutcome:
    """Start a known service. Prefers `brew services start <name>`."""
    if dry_run:
        record("services.start.dry-run", name=svc.name, kind=svc.kind)
        return ServiceOutcome(svc.name, "start", True, "dry-run: would start")

    if svc.brew_managed and _brew_available():
        ok, msg = _run_brew("start", svc.name)
        record(
            "services.start",
            name=svc.name,
            kind=svc.kind,
            via="brew",
            ok=ok,
            message=msg[:200],
        )
        return ServiceOutcome(svc.name, "start", ok, msg)

    record(
        "services.start",
        name=svc.name,
        kind=svc.kind,
        via="none",
        ok=False,
        message="no start path (brew required)",
    )
    return ServiceOutcome(
        svc.name,
        "start",
        False,
        "cannot start: service is not brew-managed and no launcher known",
    )


def stop(svc: ServiceInfo, *, dry_run: bool = False) -> ServiceOutcome:
    """Stop a known service. Prefer brew when available, else SIGTERM."""
    if dry_run:
        record("services.stop.dry-run", name=svc.name, kind=svc.kind, pid=svc.pid)
        return ServiceOutcome(svc.name, "stop", True, "dry-run: would stop")

    if svc.brew_managed and _brew_available():
        ok, msg = _run_brew("stop", svc.name)
        record(
            "services.stop",
            name=svc.name,
            kind=svc.kind,
            via="brew",
            pid=svc.pid,
            ok=ok,
            message=msg[:200],
        )
        return ServiceOutcome(svc.name, "stop", ok, msg)

    if svc.pid is None:
        record(
            "services.stop",
            name=svc.name,
            kind=svc.kind,
            via="none",
            ok=False,
            message="no pid",
        )
        return ServiceOutcome(svc.name, "stop", False, "no pid to signal")

    ok, msg = _terminate_pid(svc.pid)
    record(
        "services.stop",
        name=svc.name,
        kind=svc.kind,
        via="signal",
        pid=svc.pid,
        ok=ok,
        message=msg[:200],
    )
    return ServiceOutcome(svc.name, "stop", ok, msg)

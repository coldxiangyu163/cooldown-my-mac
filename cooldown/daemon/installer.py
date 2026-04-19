"""launchd installer for the cooldown daemon.

Renders `templates/cooldown.plist` into `~/Library/LaunchAgents/` and
bootstraps it into the current GUI session. Idempotent: re-running
`install()` gracefully replaces an existing agent.
"""
from __future__ import annotations

import os
import re
import shlex
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

from ..safety.oplog import record

LABEL = "ai.cooldown.agent"
TEMPLATE_PATH = Path(__file__).parent / "templates" / "cooldown.plist"


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------


def plist_path() -> Path:
    return Path("~/Library/LaunchAgents/ai.cooldown.agent.plist").expanduser()


def _log_dir() -> Path:
    return Path("~/Library/Logs/cooldown").expanduser()


def _working_directory() -> Path:
    return Path("~").expanduser()


def resolve_executable() -> list[str]:
    """Return the argv list that runs `cool daemon run`.

    Prefers a `cool` binary on PATH; falls back to the current Python
    interpreter invoking the module. The caller is expected to append the
    `daemon run` subcommand.
    """
    cool = shutil.which("cool")
    if cool:
        return [cool]
    return [sys.executable, "-m", "cooldown.cli"]


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def _render_plist(argv: list[str], *, log_path: Path, stderr_path: Path) -> str:
    template = TEMPLATE_PATH.read_text(encoding="utf-8")
    program_arguments = "\n".join(
        f"        <string>{_xml_escape(a)}</string>" for a in argv
    )
    rendered = (
        template.replace("{{LABEL}}", LABEL)
        .replace("{{PROGRAM_ARGUMENTS}}", program_arguments)
        .replace("{{LOG_PATH}}", _xml_escape(str(log_path)))
        .replace("{{STDERR_PATH}}", _xml_escape(str(stderr_path)))
        .replace("{{WORKING_DIRECTORY}}", _xml_escape(str(_working_directory())))
        # EXECUTABLE placeholder left in docs for caller clarity.
        .replace("{{EXECUTABLE}}", _xml_escape(argv[0]))
    )
    return rendered


def _xml_escape(s: str) -> str:
    return (
        s.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


# ---------------------------------------------------------------------------
# Outcome
# ---------------------------------------------------------------------------


@dataclass
class InstallOutcome:
    ok: bool
    plist_path: Path
    messages: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# launchctl wrappers
# ---------------------------------------------------------------------------


def _uid() -> int:
    return os.getuid()


def _launchctl(args: list[str], *, check: bool = False) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["launchctl", *args],
        check=check,
        capture_output=True,
        text=True,
        timeout=15,
    )


def _domain_target() -> str:
    return f"gui/{_uid()}"


def _service_target() -> str:
    return f"{_domain_target()}/{LABEL}"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def install(
    executable: str | list[str] | None = None,
    *,
    dry_run: bool = False,
    force: bool = False,
) -> InstallOutcome:
    """Install (or refresh) the launchd agent.

    `executable` may be a single binary path (the " daemon run" arguments
    are appended automatically) or a full argv list (appended as-is). When
    omitted, uses `resolve_executable()`.
    """
    if executable is None:
        base_argv = resolve_executable()
    elif isinstance(executable, str):
        base_argv = shlex.split(executable) if " " in executable else [executable]
    else:
        base_argv = list(executable)

    # Whatever the user passed, make sure the subcommand is in there.
    argv = base_argv if any(a == "run" for a in base_argv[1:]) else [*base_argv, "daemon", "run"]

    log_dir = _log_dir()
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / "stdout.log"
    stderr_path = log_dir / "stderr.log"

    target = plist_path()
    rendered = _render_plist(argv, log_path=log_path, stderr_path=stderr_path)

    messages: list[str] = []
    if dry_run:
        messages.append(f"dry-run: would write {target}")
        messages.append(f"dry-run: would launchctl bootstrap {_domain_target()} {target}")
        record("daemon.install", dry_run=True, plist=str(target))
        return InstallOutcome(ok=True, plist_path=target, messages=messages)

    if target.exists() and not force:
        # Idempotent overwrite is fine; we always re-render.
        messages.append(f"refreshing existing plist at {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(rendered, encoding="utf-8")
    os.chmod(target, 0o644)
    messages.append(f"wrote {target}")

    # Best-effort bootout of any stale service.
    bootout = _launchctl(["bootout", _service_target()])
    if bootout.returncode == 0:
        messages.append(f"bootout {_service_target()} ok")
    else:
        # Service wasn't loaded — fine.
        messages.append(f"bootout: {(bootout.stderr or bootout.stdout).strip() or 'not loaded'}")

    bootstrap = _launchctl(["bootstrap", _domain_target(), str(target)])
    if bootstrap.returncode != 0:
        err = (bootstrap.stderr or bootstrap.stdout).strip()
        messages.append(f"bootstrap failed: {err}")
        record("daemon.install", ok=False, plist=str(target), error=err)
        return InstallOutcome(ok=False, plist_path=target, messages=messages)
    messages.append(f"bootstrap {_domain_target()} ok")

    enable = _launchctl(["enable", _service_target()])
    if enable.returncode == 0:
        messages.append(f"enable {_service_target()} ok")
    else:
        messages.append(f"enable: {(enable.stderr or enable.stdout).strip() or 'skipped'}")

    record("daemon.install", ok=True, plist=str(target), argv=argv)
    return InstallOutcome(ok=True, plist_path=target, messages=messages)


def uninstall(*, dry_run: bool = False) -> InstallOutcome:
    target = plist_path()
    messages: list[str] = []

    if dry_run:
        messages.append(f"dry-run: would bootout {_service_target()}")
        messages.append(f"dry-run: would delete {target}")
        record("daemon.uninstall", dry_run=True, plist=str(target))
        return InstallOutcome(ok=True, plist_path=target, messages=messages)

    bootout = _launchctl(["bootout", _service_target()])
    if bootout.returncode == 0:
        messages.append(f"bootout {_service_target()} ok")
    else:
        messages.append(f"bootout: {(bootout.stderr or bootout.stdout).strip() or 'not loaded'}")

    if target.exists():
        try:
            target.unlink()
            messages.append(f"removed {target}")
        except OSError as exc:
            messages.append(f"remove failed: {exc}")
            record("daemon.uninstall", ok=False, plist=str(target), error=str(exc))
            return InstallOutcome(ok=False, plist_path=target, messages=messages)
    else:
        messages.append(f"no plist at {target}")

    record("daemon.uninstall", ok=True, plist=str(target))
    return InstallOutcome(ok=True, plist_path=target, messages=messages)


def status() -> dict[str, object]:
    """Introspect the agent state via `launchctl print`.

    Never raises; missing pieces come back as None.
    """
    target = plist_path()
    installed = target.exists()
    pid: int | None = None
    last_exit_status: int | None = None

    try:
        r = _launchctl(["print", _service_target()])
        if r.returncode == 0:
            for line in r.stdout.splitlines():
                m = re.match(r"\s*pid\s*=\s*(\d+)", line)
                if m:
                    pid = int(m.group(1))
                m2 = re.match(r"\s*last exit (?:code|status)\s*=\s*(-?\d+)", line)
                if m2:
                    last_exit_status = int(m2.group(1))
    except (FileNotFoundError, subprocess.SubprocessError):
        pass

    log_tail: list[str] = []
    log_file = _log_dir() / "daemon.log"
    if log_file.exists():
        try:
            with log_file.open("r", encoding="utf-8", errors="replace") as f:
                log_tail = [line.rstrip("\n") for line in f.readlines()[-10:]]
        except OSError:
            pass

    return {
        "installed": installed,
        "plist_path": str(target),
        "pid": pid,
        "last_exit_status": last_exit_status,
        "log_tail": log_tail,
        "label": LABEL,
        "service_target": _service_target(),
    }

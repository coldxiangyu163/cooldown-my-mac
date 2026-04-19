"""Disable / re-enable launchd jobs via ``launchctl bootout`` / ``bootstrap``.

Self-defense: we refuse to touch anything classified as ``apple`` — these
are system-managed agents and disabling them can leave the machine in a
weird state. Everything we do flows through the oplog so actions can be
audited after the fact.
"""
from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass

from ..collectors.launchd import LaunchdEntry
from ..safety.oplog import record


@dataclass
class LaunchdOutcome:
    label: str
    action: str  # "disable" | "enable"
    ok: bool
    message: str


def _uid() -> int:
    return os.getuid()


def _target(entry: LaunchdEntry) -> str:
    """Return the service target string understood by launchctl."""
    if entry.domain == "system":
        return f"system/{entry.label}"
    # user and gui domains both use the caller's uid
    return f"{entry.domain}/{_uid()}/{entry.label}"


def _run(cmd: list[str], *, timeout: float = 10.0) -> tuple[int, str]:
    try:
        r = subprocess.run(cmd, check=False, capture_output=True, text=True, timeout=timeout)
    except FileNotFoundError:
        return 127, "launchctl not found"
    except subprocess.SubprocessError as e:
        return -1, f"subprocess error: {e}"
    return r.returncode, (r.stderr or r.stdout or "").strip()


def disable(entry: LaunchdEntry, *, dry_run: bool = False) -> LaunchdOutcome:
    """``launchctl bootout`` the given entry (requires sudo for system)."""
    if entry.category == "apple":
        msg = "refuses to disable Apple-owned agent"
        record(
            "launchd.disable.refused",
            label=entry.label,
            category=entry.category,
            reason=msg,
        )
        return LaunchdOutcome(entry.label, "disable", False, msg)

    target = _target(entry)
    cmd: list[str]
    if entry.domain == "system":
        cmd = ["sudo", "-n", "launchctl", "bootout", target]
    else:
        cmd = ["launchctl", "bootout", target]

    if dry_run:
        record(
            "launchd.disable.dry-run",
            label=entry.label,
            domain=entry.domain,
            category=entry.category,
        )
        return LaunchdOutcome(
            entry.label,
            "disable",
            True,
            "dry-run: " + " ".join(cmd),
        )

    rc, msg = _run(cmd)
    ok = rc == 0
    record(
        "launchd.disable",
        label=entry.label,
        domain=entry.domain,
        category=entry.category,
        rc=rc,
        ok=ok,
        message=msg[:200],
    )
    return LaunchdOutcome(
        entry.label,
        "disable",
        ok,
        msg or ("booted out" if ok else f"rc={rc}"),
    )


def enable(entry: LaunchdEntry, *, dry_run: bool = False) -> LaunchdOutcome:
    """``launchctl bootstrap`` the entry's plist back into its domain."""
    if entry.category == "apple":
        msg = "refuses to act on Apple-owned agent"
        record("launchd.enable.refused", label=entry.label, reason=msg)
        return LaunchdOutcome(entry.label, "enable", False, msg)

    if not entry.path:
        return LaunchdOutcome(
            entry.label,
            "enable",
            False,
            "no plist path known — cannot bootstrap",
        )

    domain_spec: str
    if entry.domain == "system":
        domain_spec = "system"
        cmd = ["sudo", "-n", "launchctl", "bootstrap", domain_spec, entry.path]
    else:
        domain_spec = f"{entry.domain}/{_uid()}"
        cmd = ["launchctl", "bootstrap", domain_spec, entry.path]

    if dry_run:
        record("launchd.enable.dry-run", label=entry.label, path=entry.path)
        return LaunchdOutcome(
            entry.label,
            "enable",
            True,
            "dry-run: " + " ".join(cmd),
        )

    rc, msg = _run(cmd)
    ok = rc == 0
    record(
        "launchd.enable",
        label=entry.label,
        path=entry.path,
        domain=entry.domain,
        rc=rc,
        ok=ok,
        message=msg[:200],
    )
    return LaunchdOutcome(
        entry.label,
        "enable",
        ok,
        msg or ("bootstrapped" if ok else f"rc={rc}"),
    )

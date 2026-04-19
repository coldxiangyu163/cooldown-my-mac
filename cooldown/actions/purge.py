"""Wrappers around macOS `purge` and `dynamic_pager` tuning."""
from __future__ import annotations

import subprocess
from dataclasses import dataclass


@dataclass
class PurgeResult:
    ok: bool
    needs_sudo: bool
    message: str


def purge(*, dry_run: bool = False) -> PurgeResult:
    """Run `sudo -n purge` which forces the disk cache to be purged.

    Requires sudo. If sudo credentials are not cached, we don't prompt (so
    this is safe to call from a daemon). Returns needs_sudo=True in that
    case so the caller can surface a helpful message.
    """
    if dry_run:
        return PurgeResult(True, False, "dry-run: would invoke `sudo -n purge`")
    try:
        r = subprocess.run(
            ["sudo", "-n", "purge"],
            check=False,
            capture_output=True,
            text=True,
            timeout=60,
        )
    except FileNotFoundError:
        return PurgeResult(False, False, "`sudo` not found")
    except subprocess.TimeoutExpired:
        return PurgeResult(False, False, "`purge` timed out (>60s)")

    if r.returncode == 0:
        return PurgeResult(True, False, "purge completed")
    combined = (r.stderr or "") + (r.stdout or "")
    if "password is required" in combined or "a terminal is required" in combined:
        return PurgeResult(False, True, "sudo password required — run `sudo -v` first")
    return PurgeResult(False, False, combined.strip() or f"purge failed (rc={r.returncode})")

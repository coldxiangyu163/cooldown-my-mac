"""Inspect + mutate macOS sleep policy via ``pmset``.

All writes go through ``sudo -n`` (no interactive prompt). We also remain
idempotent: if the policy already matches, we skip the subprocess call and
log a ``sleep_policy.noop`` instead.
"""
from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from typing import Literal

from ..safety.oplog import record

SleepSource = Literal["ac", "battery", "all"]

_SOURCE_FLAG: dict[SleepSource, str] = {
    "ac": "-c",
    "battery": "-b",
    "all": "-a",
}

_DEFAULT_DISPLAYSLEEP = 10
_DEFAULT_DISKSLEEP = 10
_DEFAULT_POWERNAP = 0


@dataclass
class SleepPolicy:
    displaysleep: int
    disksleep: int
    powernap: bool


@dataclass
class ApplyOutcome:
    ok: bool
    changed: bool
    message: str


def _pmset_g() -> str:
    try:
        r = subprocess.run(
            ["pmset", "-g"], check=False, capture_output=True, text=True, timeout=3
        )
    except (subprocess.SubprocessError, FileNotFoundError):
        return ""
    return r.stdout or ""


def _int_field(text: str, key: str) -> int | None:
    m = re.search(rf"\b{key}\s+(\d+)", text)
    return int(m.group(1)) if m else None


def current() -> SleepPolicy:
    """Return the live macOS sleep policy (as reported by ``pmset -g``).

    Falls back to sensible defaults when pmset output is missing a field.
    """
    out = _pmset_g()
    displaysleep = _int_field(out, "displaysleep")
    disksleep = _int_field(out, "disksleep")
    powernap = _int_field(out, "powernap")
    return SleepPolicy(
        displaysleep=displaysleep if displaysleep is not None else -1,
        disksleep=disksleep if disksleep is not None else -1,
        powernap=bool(powernap) if powernap is not None else False,
    )


def _sudo_pmset(args: list[str], *, dry_run: bool) -> ApplyOutcome:
    cmd = ["sudo", "-n", "pmset", *args]
    if dry_run:
        return ApplyOutcome(True, True, "dry-run: " + " ".join(cmd))
    try:
        r = subprocess.run(cmd, check=False, capture_output=True, text=True, timeout=10)
    except FileNotFoundError:
        return ApplyOutcome(False, False, "`sudo` not found")
    except subprocess.SubprocessError as e:
        return ApplyOutcome(False, False, f"sudo error: {e}")
    if r.returncode == 0:
        return ApplyOutcome(True, True, "applied")
    combined = (r.stderr or "") + (r.stdout or "")
    if "password is required" in combined or "a terminal is required" in combined:
        return ApplyOutcome(False, False, "sudo password required — run `sudo -v` first")
    return ApplyOutcome(False, False, combined.strip() or f"pmset failed (rc={r.returncode})")


def apply(
    policy: SleepPolicy,
    *,
    source: SleepSource = "ac",
    dry_run: bool = False,
) -> ApplyOutcome:
    """Apply the requested ``SleepPolicy`` on the given power source.

    Idempotent: if ``pmset -g`` already reports the same displaysleep /
    disksleep, we short-circuit and return ``changed=False``.
    """
    flag = _SOURCE_FLAG[source]
    live = current()
    if (
        live.displaysleep == policy.displaysleep
        and live.disksleep == policy.disksleep
    ):
        record(
            "sleep_policy.noop",
            source=source,
            displaysleep=policy.displaysleep,
            disksleep=policy.disksleep,
        )
        return ApplyOutcome(True, False, "no-op: policy already matches")

    args = [
        flag,
        "displaysleep",
        str(policy.displaysleep),
        "disksleep",
        str(policy.disksleep),
    ]
    outcome = _sudo_pmset(args, dry_run=dry_run)
    record(
        "sleep_policy.apply",
        source=source,
        displaysleep=policy.displaysleep,
        disksleep=policy.disksleep,
        powernap=policy.powernap,
        dry_run=dry_run,
        ok=outcome.ok,
        message=outcome.message[:200],
    )
    return outcome


def restore_defaults(*, dry_run: bool = False) -> ApplyOutcome:
    """Restore the sane macOS defaults on AC power.

    * ``displaysleep`` = 10 min
    * ``disksleep``   = 10 min
    * ``powernap``    = off
    """
    policy = SleepPolicy(
        displaysleep=_DEFAULT_DISPLAYSLEEP,
        disksleep=_DEFAULT_DISKSLEEP,
        powernap=bool(_DEFAULT_POWERNAP),
    )
    outcome = apply(policy, source="ac", dry_run=dry_run)
    # Best-effort powernap disable; surface its failure but don't block.
    if outcome.ok and outcome.changed:
        _sudo_pmset(["-c", "powernap", str(_DEFAULT_POWERNAP)], dry_run=dry_run)
    record(
        "sleep_policy.restore_defaults",
        dry_run=dry_run,
        ok=outcome.ok,
        changed=outcome.changed,
    )
    return outcome

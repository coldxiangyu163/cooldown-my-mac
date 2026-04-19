"""SMC / powermetrics sampler.

Best-effort readings of die temperatures, fan RPM, and package power from
``powermetrics``. Because ``powermetrics`` requires root, we never attempt
``sudo`` interactively — we only run ``sudo -n`` which succeeds when either
the user has cached sudo credentials or there is an entry in
``/etc/sudoers.d`` granting NOPASSWD for powermetrics.

If the command is unavailable we return an ``unavailable`` reading and the
caller can show ``sudoers_hint()`` to the user.
"""
from __future__ import annotations

import plistlib
import re
import subprocess
from dataclasses import dataclass


@dataclass
class SmcReading:
    source: str  # "powermetrics" | "iostat" | "unavailable"
    cpu_die_temp: float | None = None  # celsius
    gpu_die_temp: float | None = None
    fan_rpm: float | None = None
    cpu_power_w: float | None = None
    gpu_power_w: float | None = None
    package_power_w: float | None = None


_SUDOERS_SNIPPET = """# /etc/sudoers.d/cooldown
# Allow the `cool thermal` command to query SMC sensors without a password.
# Install with:
#   sudo visudo -f /etc/sudoers.d/cooldown
# (replace YOUR_USER below).
YOUR_USER ALL=(root) NOPASSWD: /usr/bin/powermetrics
"""


def sudoers_hint() -> str:
    """Return a ready-to-paste sudoers.d snippet enabling passwordless
    powermetrics. Shown to the user when the sampler is unavailable.
    """
    return _SUDOERS_SNIPPET


def _run_powermetrics(timeout: float) -> tuple[bytes, str]:
    """Return (stdout_bytes, stderr_text). Never raises."""
    try:
        r = subprocess.run(
            [
                "sudo",
                "-n",
                "powermetrics",
                "--samplers",
                "smc,cpu_power,gpu_power",
                "-n",
                "1",
                "-i",
                "100",
                "--format",
                "plist",
            ],
            check=False,
            capture_output=True,
            timeout=timeout,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return b"", "timeout-or-missing"
    return r.stdout or b"", (r.stderr.decode("utf-8", "replace") if r.stderr else "")


def _parse_plist(blob: bytes) -> SmcReading | None:
    """Try to parse powermetrics plist output. Returns None on failure.

    powermetrics streams a sequence of plist documents separated by NULs.
    We only care about the first one with ``-n 1``.
    """
    if not blob:
        return None
    # Strip anything before the first plist header and after the last </plist>.
    start = blob.find(b"<?xml")
    if start == -1:
        return None
    end = blob.rfind(b"</plist>")
    if end == -1:
        return None
    chunk = blob[start : end + len(b"</plist>")]
    try:
        data = plistlib.loads(chunk)
    except Exception:  # noqa: BLE001 — plistlib can raise a few types
        return None
    if not isinstance(data, dict):
        return None

    reading = SmcReading(source="powermetrics")

    # SMC block — key names vary between Intel / Apple Silicon / macOS
    # releases, so we probe a few likely shapes.
    smc = data.get("smc") or data.get("SMC")
    if isinstance(smc, dict):
        reading.cpu_die_temp = _first_float(
            smc,
            ("cpu_die_temperature", "cpu_die_temp", "CPU die temperature"),
        )
        reading.gpu_die_temp = _first_float(
            smc,
            ("gpu_die_temperature", "gpu_die_temp", "GPU die temperature"),
        )
        fans = smc.get("fans") or smc.get("Fans")
        if isinstance(fans, list) and fans:
            first = fans[0]
            if isinstance(first, dict):
                reading.fan_rpm = _first_float(first, ("rpm", "RPM", "speed"))

    # Processor / CPU power block
    proc = data.get("processor") or data.get("Processor")
    if isinstance(proc, dict):
        reading.cpu_power_w = _first_float(
            proc,
            ("cpu_power", "package_watts", "cpu_energy"),
            scale=_scale_mw_to_w,
        )
        reading.package_power_w = _first_float(
            proc,
            ("package_watts", "package_power"),
            scale=_scale_mw_to_w,
        )

    gpu = data.get("gpu") or data.get("GPU")
    if isinstance(gpu, dict):
        reading.gpu_power_w = _first_float(
            gpu,
            ("gpu_power", "gpu_energy"),
            scale=_scale_mw_to_w,
        )

    return reading


def _first_float(
    d: dict,
    keys: tuple[str, ...],
    *,
    scale=lambda x: x,
) -> float | None:
    for k in keys:
        if k in d:
            try:
                return scale(float(d[k]))
            except (TypeError, ValueError):
                continue
    return None


def _scale_mw_to_w(v: float) -> float:
    # powermetrics reports several power fields in milliwatts; anything
    # above 2000 is almost certainly mW on a Mac.
    return v / 1000.0 if v > 2000 else v


_TEMP_RE = re.compile(r"([A-Za-z _-]+die temperature)[^\d]*(\d+(?:\.\d+)?)\s*C", re.I)
_FAN_RE = re.compile(r"Fan\s*\d*\s*:?[^\d]*(\d+(?:\.\d+)?)\s*rpm", re.I)
_PKG_POWER_RE = re.compile(r"(?:Package Power|CPU Power|Combined Power)\s*:?[^\d]*(\d+(?:\.\d+)?)\s*(m?W)", re.I)


def _parse_text(stdout: bytes) -> SmcReading | None:
    if not stdout:
        return None
    txt = stdout.decode("utf-8", "replace")
    reading = SmcReading(source="powermetrics")
    for m in _TEMP_RE.finditer(txt):
        label = m.group(1).lower()
        val = float(m.group(2))
        if "cpu" in label and reading.cpu_die_temp is None:
            reading.cpu_die_temp = val
        elif "gpu" in label and reading.gpu_die_temp is None:
            reading.gpu_die_temp = val
    fm = _FAN_RE.search(txt)
    if fm:
        reading.fan_rpm = float(fm.group(1))
    pm = _PKG_POWER_RE.search(txt)
    if pm:
        val = float(pm.group(1))
        if pm.group(2).lower() == "mw":
            val /= 1000.0
        reading.package_power_w = val
    # Consider the reading useful only if at least one field parsed.
    if any(
        v is not None
        for v in (
            reading.cpu_die_temp,
            reading.gpu_die_temp,
            reading.fan_rpm,
            reading.package_power_w,
        )
    ):
        return reading
    return None


def collect(timeout: float = 2.0) -> SmcReading:
    """Sample SMC / power once. Never raises, never prompts for sudo."""
    stdout, stderr = _run_powermetrics(timeout)
    if not stdout:
        return SmcReading(source="unavailable")
    if "a terminal is required" in stderr or "password is required" in stderr:
        return SmcReading(source="unavailable")

    reading = _parse_plist(stdout)
    if reading is None:
        reading = _parse_text(stdout)
    if reading is None:
        return SmcReading(source="unavailable")
    return reading

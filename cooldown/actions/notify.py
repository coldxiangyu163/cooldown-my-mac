"""macOS native notifications via osascript (no extra deps)."""
from __future__ import annotations

import shlex
import subprocess


def notify(title: str, message: str, *, subtitle: str | None = None, sound: str | None = None) -> bool:
    """Display a Notification Center alert. Silently returns False on failure."""
    parts = [f'display notification {shlex.quote(message)} with title {shlex.quote(title)}']
    if subtitle:
        parts.append(f"subtitle {shlex.quote(subtitle)}")
    if sound:
        parts.append(f"sound name {shlex.quote(sound)}")
    script = " ".join(parts)
    try:
        subprocess.run(
            ["osascript", "-e", script],
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
        return True
    except (subprocess.SubprocessError, FileNotFoundError):
        return False

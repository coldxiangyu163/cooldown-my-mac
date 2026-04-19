"""Interactive confirmation helpers with safe defaults."""
from __future__ import annotations

from rich.console import Console
from rich.prompt import Confirm

_console = Console()


def confirm(message: str, *, default: bool = False, assume_yes: bool = False) -> bool:
    if assume_yes:
        _console.print(f"[yellow]auto-yes[/yellow] {message}")
        return True
    try:
        return Confirm.ask(message, default=default, console=_console)
    except (EOFError, KeyboardInterrupt):
        _console.print("[red]aborted[/red]")
        return False

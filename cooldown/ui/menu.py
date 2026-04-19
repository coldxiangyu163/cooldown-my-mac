"""Interactive main menu (invoked when `cool` is called without a subcommand)."""
from __future__ import annotations

import questionary
from rich.console import Console

CHOICES: list[tuple[str, str]] = [
    ("status", "System health dashboard"),
    ("procs", "AI CLI inventory + interactive kill"),
    ("reap", "Reap idle droid/codex/claude/tmux sessions"),
    ("reap-dry", "Reap — dry-run preview"),
    ("pressure", "Memory pressure one-shot check"),
    ("pressure-watch", "Memory pressure watch loop (notifies)"),
    ("quit", "Quit"),
]


def run(console: Console) -> str | None:
    try:
        ans = questionary.select(
            "cooldown · what would you like to do?",
            choices=[questionary.Choice(f"{k:<10} {v}", value=k) for k, v in CHOICES],
            use_shortcuts=False,
            qmark="›",
        ).ask()
    except KeyboardInterrupt:
        return None
    return ans

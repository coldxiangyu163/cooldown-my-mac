"""Interactive main menu (invoked when `cool` is called without a subcommand)."""
from __future__ import annotations

import questionary
from rich.console import Console

CHOICES: list[tuple[str, str]] = [
    ("status", "System health dashboard"),
    ("watch", "Full-screen live TUI (textual)"),
    ("procs", "AI CLI inventory + interactive kill"),
    ("reap", "Reap idle droid/codex/claude/tmux sessions"),
    ("reap-dry", "Reap — dry-run preview"),
    ("pressure", "Memory pressure one-shot check"),
    ("pressure-watch", "Memory pressure watch loop (notifies)"),
    ("services", "Start/stop dev services (mysql/postgres/redis/...)"),
    ("apps-list", "Heavy background apps — list"),
    ("apps-suspend", "Heavy background apps — suspend (SIGSTOP)"),
    ("apps-resume", "Heavy background apps — resume (SIGCONT)"),
    ("thermal", "Thermal + sleep policy dashboard"),
    ("launchd", "Launchd agents — summary"),
    ("launchd-audit", "Launchd agents — audit + disable"),
    ("daemon-status", "Background daemon status"),
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

"""`cool watch` — Textual full-screen live dashboard.

Meant to run inside a tmux/cmux pane 24/7. Ticks every ``interval`` seconds
and refreshes the same CPU / Memory / Thermal / AI CLI panels that
``cool status`` renders in one-shot mode.

Textual is imported lazily inside :func:`run` so the rest of the CLI keeps
working even if the optional dependency is missing.

Blocking collectors
-------------------
``cooldown.collectors.system.collect`` runs ``psutil.cpu_percent(interval=...)``
and ``cooldown.collectors.procs.collect`` sleeps for a short sampling window
so CPU accounting is non-zero. Rather than freeze the event loop, every tick
is dispatched to a Textual thread worker via :meth:`App.run_worker` and the
results are delivered back to the UI through :meth:`App.call_from_thread`.
We also shrink the ``procs`` sample window from the default 0.25s to 0.1s to
keep refresh latency low.
"""
from __future__ import annotations

import contextlib

from rich.console import Console

from ..collectors import memory as mem_mod
from ..collectors import procs as procs_mod
from ..collectors import system as sys_mod
from ..collectors import thermal as therm_mod
from .dashboard import _cli_panel, _cpu_panel, _mem_panel, _thermal_panel


def _build_app_class():
    """Import textual lazily and return the :class:`CooldownWatchApp` class.

    Kept as a factory so ``import cooldown.ui.watch`` does not trigger a
    textual import at module load time.
    """
    from textual.app import App
    from textual.containers import Horizontal
    from textual.widgets import Footer, Header, Static

    class CooldownWatchApp(App):
        """Full-screen live dashboard for ``cool watch``."""

        TITLE = "cooldown · watch"

        CSS = """
        Screen {
            layout: vertical;
        }
        Header {
            dock: top;
        }
        Footer {
            dock: bottom;
        }
        .row {
            height: 1fr;
            width: 100%;
        }
        .panel {
            border: round $primary;
            padding: 0 1;
            width: 1fr;
            height: 1fr;
            content-align: left top;
        }
        """

        BINDINGS = [
            ("q", "quit", "Quit"),
            ("r", "refresh_now", "Refresh"),
            ("p", "toggle_pause", "Pause/Resume"),
            ("k", "kill_selected", "Kill"),
            ("plus,equals_sign", "faster", "Faster"),
            ("minus,underscore", "slower", "Slower"),
        ]

        def __init__(self, interval: int = 3) -> None:
            super().__init__()
            self.interval = max(1, int(interval))
            self.paused = False
            self._timer = None

        # --------------------------------------------------------------- layout
        def compose(self):
            yield Header(show_clock=True)
            yield Horizontal(
                Static("[dim]sampling…[/]", id="cpu", classes="panel"),
                Static("[dim]sampling…[/]", id="mem", classes="panel"),
                classes="row",
            )
            yield Horizontal(
                Static("[dim]sampling…[/]", id="thermal", classes="panel"),
                Static("[dim]sampling…[/]", id="cli", classes="panel"),
                classes="row",
            )
            yield Footer()

        # --------------------------------------------------------------- tick
        def on_mount(self) -> None:
            self._reset_timer()
            self._schedule_refresh()

        def _reset_timer(self) -> None:
            if self._timer is not None:
                self._timer.stop()
            self._timer = self.set_interval(self.interval, self._schedule_refresh)

        def _schedule_refresh(self) -> None:
            if self.paused:
                return
            # Collectors block (psutil sampling, vm_stat, pmset) — keep them
            # off the UI thread.
            self.run_worker(self._gather, thread=True, exclusive=True, group="cooldown")

        def _gather(self) -> None:
            # Every collector call is isolated so one flaky probe (macOS
            # sysctl EPERM, a transient Zombie, etc.) cannot take down the
            # whole TUI. Worst case for a single tick is a partial refresh
            # with the offending panel showing its last-known values.
            try:
                sys_stats = sys_mod.collect(cpu_sample=0.1)
            except Exception as exc:  # noqa: BLE001
                self.call_from_thread(self._set_error, "cpu", exc)
                return
            try:
                mem = mem_mod.collect()
            except Exception as exc:  # noqa: BLE001
                self.call_from_thread(self._set_error, "mem", exc)
                return
            try:
                therm = therm_mod.collect()
            except Exception as exc:  # noqa: BLE001
                self.call_from_thread(self._set_error, "thermal", exc)
                return
            try:
                procs = procs_mod.collect(sample_interval=0.1)
                procs_mod.enrich_idle(procs)
                procs.sort(key=lambda p: -p.rss)
            except Exception as exc:  # noqa: BLE001
                self.call_from_thread(self._set_error, "cli", exc)
                return
            self.call_from_thread(self._apply, sys_stats, mem, therm, procs)

        def _set_error(self, panel_id: str, exc: BaseException) -> None:
            with contextlib.suppress(Exception):
                self.query_one(f"#{panel_id}", Static).update(
                    f"[red]collector error[/]\n[dim]{type(exc).__name__}: {exc}[/]"
                )

        def _apply(self, sys_stats, mem, therm, procs) -> None:
            self.query_one("#cpu", Static).update(_cpu_panel(sys_stats))
            self.query_one("#mem", Static).update(_mem_panel(mem))
            self.query_one("#thermal", Static).update(_thermal_panel(therm))
            self.query_one("#cli", Static).update(_cli_panel(procs))
            self.sub_title = (
                f"every {self.interval}s"
                + ("  ·  [yellow]paused[/]" if self.paused else "")
            )

        # --------------------------------------------------------------- actions
        def action_refresh_now(self) -> None:
            self._schedule_refresh()
            self.notify("refreshed", timeout=1.5)

        def action_toggle_pause(self) -> None:
            self.paused = not self.paused
            self.notify("paused" if self.paused else "resumed", timeout=1.5)
            # Reflect state in the subtitle even when paused.
            self.sub_title = (
                f"every {self.interval}s"
                + ("  ·  [yellow]paused[/]" if self.paused else "")
            )

        def action_kill_selected(self) -> None:
            self.notify(
                "row-based kill picker not yet implemented — use `cool reap`",
                severity="warning",
                timeout=2.5,
            )

        def action_faster(self) -> None:
            self.interval = max(1, self.interval - 1)
            self._reset_timer()
            self.notify(f"interval: {self.interval}s", timeout=1.5)

        def action_slower(self) -> None:
            self.interval = min(60, self.interval + 1)
            self._reset_timer()
            self.notify(f"interval: {self.interval}s", timeout=1.5)

    return CooldownWatchApp


def run(console: Console, *, interval: int = 3) -> int:
    """Launch the ``cool watch`` full-screen dashboard.

    Returns 0 on clean exit, non-zero if textual is not installed.
    """
    try:
        app_cls = _build_app_class()
    except ImportError:
        console.print(
            "[red]textual is not installed[/] — required for `cool watch`.\n"
            "[dim]install it with one of:[/]\n"
            "  [cyan]pipx inject cooldown-my-mac textual[/]\n"
            "  [cyan]pip install textual[/]"
        )
        return 1
    app = app_cls(interval=interval)
    app.run()
    return 0

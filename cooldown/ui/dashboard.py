"""`cool status` one-shot dashboard (Rich, mimicking Mole's layout)."""
from __future__ import annotations

import json
import os
import platform
from dataclasses import asdict, is_dataclass
from typing import Any

from rich.box import SIMPLE
from rich.columns import Columns
from rich.console import Console, Group
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from ..collectors import battery as batt_mod
from ..collectors import hot_procs as hot_mod
from ..collectors import leftovers as leftovers_mod
from ..collectors import memory as mem_mod
from ..collectors import procs as procs_mod
from ..collectors import system as sys_mod
from ..collectors import thermal as therm_mod
from ..util import bar, heatbar, human_bytes, human_duration

# ---------------------------------------------------------------------------
# Severity colour policy (keep in lock-step across all panels)
# ---------------------------------------------------------------------------
#   ok / normal / safe        → green
#   notable / active / accent → cyan          (only for the "active but
#                                              not stressed" mid-band)
#   warn / approaching limit  → yellow        (plain, never bold)
#   critical / outlier / hot  → bold red      (only place where bold +
#                                              red combine — reserves
#                                              that weight for trouble)
#
# Health-score colour uses the same scale, just compressed because it's
# already a 0–100 abstraction rather than a raw percent.

def _pct_color(pct: float) -> str:
    if pct >= 90:
        return "bold red"
    if pct >= 75:
        return "yellow"
    if pct >= 50:
        return "cyan"
    return "green"


# ---------------------------------------------------------------------------
# Border-title summaries — keep the panel self-documenting at a glance
# ---------------------------------------------------------------------------
# Each info panel exposes a small ``title_summary_*`` helper that returns
# the markup for "noun [dim]· severity-dot headline-value[/]". The tables
# already follow this pattern (rounds 3); these helpers extend it to the
# four info panels so the entire grid shares one title rhythm.

def cpu_title_summary(sys_stats: sys_mod.SystemStats) -> str:
    """Return ``CPU  · ● 40.9%`` style border-title markup."""
    pct = sys_stats.cpu_percent
    color = _pct_color(pct)
    return f"CPU  [dim]·[/] [{color}]●[/] [{color}]{pct:.1f}%[/]"


def mem_title_summary(mem: mem_mod.MemoryStats) -> str:
    """Return ``Memory  · ● 73.8% · critical`` style border-title markup.

    Pressure level is appended as a dim suffix when it escalates to
    warn/critical so the title alone tells you "memory is in trouble"
    without needing to look at the Pressure row.
    """
    pct = mem.used_percent
    color = _pct_color(pct)
    base = f"Memory  [dim]·[/] [{color}]●[/] [{color}]{pct:.1f}%[/]"
    lvl = (mem.pressure_level or "").lower()
    if lvl == "critical":
        base += "  [bold red]· critical[/]"
    elif lvl == "warn":
        base += "  [yellow]· warn[/]"
    return base


def thermal_title_summary(t: therm_mod.ThermalStats) -> str:
    """Return ``Thermal  · ● ok`` / ``▲ throttled`` style markup."""
    if t.thermal_warning and t.thermal_warning != "none":
        return f"Thermal  [dim]·[/] [bold red]▲ {t.thermal_warning}[/]"
    if "throttled" in (t.cpu_power_status or "").lower():
        return "Thermal  [dim]·[/] [bold red]▲ throttled[/]"
    if t.sleep_prevented:
        return "Thermal  [dim]·[/] [bold red]▲ sleep blocked[/]"
    if t.low_power_mode:
        return "Thermal  [dim]·[/] [yellow]◆ low-power[/]"
    return "Thermal  [dim]·[/] [green]● ok[/]"


def battery_title_summary(b: batt_mod.BatteryStats | None) -> str:
    """Return ``Battery  · ● 100% · 30.6°C`` style markup.

    Both Level and Temp get their own severity dot — they're the two
    independent axes the user cares about (charge state + heat).
    """
    if b is None:
        return "Battery  [dim]· no battery[/]"
    parts = ["Battery"]
    bits: list[str] = []
    if b.percent is not None:
        lc = "green" if b.percent >= 40 else "yellow" if b.percent >= 15 else "bold red"
        bits.append(f"[{lc}]●[/] [{lc}]{b.percent:.0f}%[/]")
    if b.temp_c is not None:
        tc = "bold red" if b.temp_c >= 40 else "yellow" if b.temp_c >= 35 else "green"
        bits.append(f"[{tc}]●[/] [{tc}]{b.temp_c:.1f}°C[/]")
    if bits:
        parts.append(f"[dim]·[/] {'  '.join(bits)}")
    return "  ".join(parts)


# ---------------------------------------------------------------------------
# AI CLI family colour palette (shared with `cool watch`)
# ---------------------------------------------------------------------------
# Each kind gets a stable colour so a glance at the inventory tells you
# "the claude block is the chunky one this morning" without reading any
# names. Colours follow vendor cues where there's a recognisable brand
# (Anthropic-ish magenta, OpenAI-ish green, Google-ish blue, GitHub
# yellow, Cursor cyan). Multiplexer kinds get a desaturated colour so
# they sit visually behind the AI CLIs.
KIND_COLORS: dict[str, str] = {
    # Anthropic / Factory / agent-driven CLIs
    "claude": "bright_magenta",
    "droid": "bright_blue",
    "hermes": "bright_cyan",
    # OpenAI / Google / Microsoft families
    "codex": "bright_green",
    "gemini": "blue",
    "copilot": "bright_yellow",
    # Cursor / IDE-attached agents
    "cursor-agent": "cyan",
    "windsurf": "bright_magenta",
    "continue": "magenta",
    "amp": "magenta",
    # Specialists
    "aider": "red",
    "opencode": "bright_red",
    "nanobot": "bright_yellow",
    "qwen": "yellow",
    "kimi": "yellow",
    "goose": "bright_white",
    "aichat": "white",
    "crush": "bright_red",
    # Multiplexers — desaturated to sit behind the AI CLIs
    "tmux": "dim cyan",
    "cmux": "dim cyan",
    "zellij": "dim cyan",
    # Orphaned automation browsers — the heavier, subtree-killing reap kind;
    # flag it red so it stands out from AI/mux candidates in the reap table.
    "automation-browser": "bright_red",
}


def kind_color(kind: str) -> str:
    return KIND_COLORS.get(kind, "yellow")


def idle_color(seconds: float) -> str:
    """Severity colour for an AI CLI session's idle duration.

    Thresholds align with ``cool reap``'s default idle gate (30 min by
    default — anything above that is the precise set the user would
    reap). Reading down the IDLE column should now answer "which rows
    are reapable?" without reading any numbers.

      * < 60s    → green   (active, do not touch)
      * < 10m    → cyan    (paused but recent)
      * < 30m    → yellow  (warming up to reapable)
      * ≥ 30m    → bold red (stale, prime candidate for reap)
    """
    if seconds >= 1800:
        return "bold red"
    if seconds >= 600:
        return "yellow"
    if seconds >= 60:
        return "cyan"
    return "green"


# ---------------------------------------------------------------------------
# Secondary palettes — langs and launchers shown in the project / ports tables
# ---------------------------------------------------------------------------
# These chips show up in the langs / launchers columns of Top Projects and
# in the launcher column of Listening Ports. Without colour, they render as
# grey comma-joined strings that the eye glosses over. Reuse the kind palette
# where there's overlap (claude/codex/tmux launchers); otherwise pick brand-
# aligned terminal colours so a user can identify "node project · started
# from VS Code" at a glance without reading the labels.
_LANG_COLORS: dict[str, str] = {
    "node":   "bright_green",
    "deno":   "bright_white",
    "bun":    "bright_yellow",
    "python": "bright_blue",
    "ruby":   "bright_red",
    "go":     "cyan",
    "rust":   "red",
    "java":   "yellow",
    "php":    "blue",
    "dotnet": "magenta",
}

_LAUNCHER_COLORS: dict[str, str] = {
    # Editor-class launchers — desaturated so they don't compete with
    # the AI CLI kinds when both are present in the same row.
    "vscode":    "bright_blue",
    "cursor":    "cyan",
    "datagrip":  "bright_magenta",
    "jetbrains": "magenta",
    "finder":    "dim",
    # System-class launchers — always dim so they read as "just the OS".
    "launchd":   "dim",
    "shell":     "dim",
    "iterm":     "dim cyan",
    "terminal":  "dim cyan",
    "unknown":   "dim",
}


def _token_color(token: str) -> str:
    """Resolve a single token to a colour, falling through three palettes.

    Order: kind (claude/codex/...) → launcher (vscode/launchd/...) → lang
    (node/python/...) → dim default. The order matters because the kind
    palette is the most established / brand-tied and should win on
    collisions.
    """
    if token in KIND_COLORS:
        return KIND_COLORS[token]
    if token in _LAUNCHER_COLORS:
        return _LAUNCHER_COLORS[token]
    if token in _LANG_COLORS:
        return _LANG_COLORS[token]
    return "dim"


def chip_tokens(s: str) -> str:
    """Render a comma-joined token list as colour-coded chips.

    Replaces raw ``"node,vscode,claude"`` cells (which read as a grey
    blob) with ``"node · vscode · claude"`` where each token carries
    its semantic colour. Tokens unknown to all three palettes render
    dim so the row remains visually quiet for noise tokens.
    """
    if not s or s == "-":
        return "[dim]–[/]"
    tokens = [t.strip() for t in s.split(",") if t.strip()]
    if not tokens:
        return "[dim]–[/]"
    return " [dim]·[/] ".join(f"[{_token_color(t)}]{t}[/]" for t in tokens)


# ---------------------------------------------------------------------------
# Top Projects name decoration (shared with `cool watch`)
# ---------------------------------------------------------------------------
# The project bucket name from dev.collect() can be a real project path
# (``search-boss``), or one of the synthesised fallback buckets
# ``(npx: …)`` / ``(app: …)`` / ``(vscode: …)`` / ``(orphan)`` /
# ``(background: …)``. We replace the wordy parenthesised prefix with a
# single icon glyph + colour so:
#   - real projects (the ones a user actually owns) read bold and stand
#     out vs the surrounding system noise
#   - synthetic buckets are visually clustered by category, dim-by-default
#   - long names (npx package paths, MCP server names) truncate cleanly
#     with an ellipsis instead of wrapping onto the next row.

BUCKET_ICONS: dict[str, tuple[str, str]] = {
    # prefix → (icon, colour)
    "npx":        ("◈", "dim cyan"),
    "app":        ("▣", "dim yellow"),
    "vscode":     ("⊟", "dim magenta"),
    "tool":       ("⊙", "dim"),
    "background": ("▸", "dim"),
}


def decorate_project_name(name: str, *, max_width: int = 32, orphan: bool = False) -> str:
    """Render a project bucket name with an icon + truncation.

    Real project names stay bold; synthesised buckets get an icon
    matching their fallback category and a dim colour so they sit
    visually behind the user's actual repos.
    """
    icon: str | None = None
    color: str = "bold"
    if name == "(orphan)":
        icon, color = "⚠", "red"
        body = "orphan"
    elif name.startswith("(") and name.endswith(")") and ":" in name:
        prefix, rest = name[1:-1].split(":", 1)
        meta = BUCKET_ICONS.get(prefix.strip())
        if meta is not None:
            icon, color = meta
            body = rest.strip()
        else:
            body = name
    else:
        body = name

    if orphan and icon is None:
        # Real on-disk project but all procs are orphans — surface the
        # signal without losing the bold project-name treatment.
        icon, color = "⚠", "bold red"

    # Reserve 2 cols for the icon + space when one is present.
    body_budget = max_width - (2 if icon else 0)
    if len(body) > body_budget:
        body = body[: max(1, body_budget - 1)] + "…"

    if icon:
        return f"[{color}]{icon}[/] [{color}]{body}[/]"
    return f"[{color}]{body}[/]"


def _kv(rows: list[tuple[str, str]]) -> Table:
    # Fixed-width label column (min_width=8) lets the four info panels
    # share a consistent left-edge rhythm — the right edges of the
    # labels in CPU / Memory / Thermal / Battery all line up at the
    # same offset from each panel's border, so the eye perceives a
    # shared "label gutter" across the grid rather than four independent
    # tables. 8 chars fits the widest label ("Pressure"); shorter
    # labels render right-justified inside the padded width.
    t = Table.grid(padding=(0, 1))
    t.add_column(style="dim", justify="right", min_width=8)
    t.add_column()
    for k, v in rows:
        t.add_row(k, v)
    return t


def cpu_content(
    sys_stats: sys_mod.SystemStats,
    *,
    history: list[float] | None = None,
) -> Table:
    """Inner CPU content (no outer Panel). Shared with `cool watch`.

    Per-core breakdown is the headline so the user can spot a single
    runaway core immediately — a 95% P-core inside a 48% average is the
    signature of a thermal bottleneck and wouldn't surface from the total
    alone. When ``history`` is supplied (recent total-CPU samples), a
    unicode sparkline is rendered next to the current value so trends
    "rising / falling / flat" are visible at a glance.
    """
    from ..collectors import hostinfo  # local import: breaks circular edge
    pct = sys_stats.cpu_percent
    color = _pct_color(pct)
    if history:
        # Per-sample severity-coloured history — recent spikes show as
        # red blocks at the right edge so "stressed for the last 30
        # seconds" reads differently from "just spiked once".
        spark = heatbar(history, hi=100.0, width=20)
        total_cell = f"[{color}]{bar(pct)} {pct:5.1f}%[/]  {spark}"
    else:
        total_cell = f"[{color}]{bar(pct)} {pct:5.1f}%[/]"
    rows: list[tuple[str, str]] = [
        ("Total", total_cell),
    ]
    host = hostinfo.collect()
    per = sys_stats.per_cpu
    if per:
        p_end = min(host.perf_cores or len(per), len(per))
        if p_end:
            p_cores = per[:p_end]
            p_avg = sum(p_cores) / p_end
            p_max = max(p_cores)
            p_hot = p_cores.index(p_max)
            # Inline per-core heatmap (btop-style): each P-core renders
            # as a single coloured block whose height = current load.
            # Avg/max numerics stay alongside for precision; the hottest
            # core's index is called out so spatial peaks read at-a-glance.
            rows.append((
                "P-cores",
                f"{heatbar(p_cores)}  "
                f"[{_pct_color(p_avg)}]avg {p_avg:5.1f}%[/]  "
                f"max [{_pct_color(p_max)}]{p_max:5.1f}%[/] "
                f"[dim]P{p_hot + 1}[/]  "
                f"[dim](×{p_end})[/]",
            ))
        if p_end < len(per):
            e = per[p_end:]
            e_avg = sum(e) / len(e)
            e_max = max(e)
            e_hot = e.index(e_max)
            rows.append((
                "E-cores",
                f"{heatbar(e)}  "
                f"[{_pct_color(e_avg)}]avg {e_avg:5.1f}%[/]  "
                f"max [{_pct_color(e_max)}]{e_max:5.1f}%[/] "
                f"[dim]E{e_hot + 1}[/]  "
                f"[dim](×{len(e)})[/]",
            ))
    # Footer strip — Load / Uptime / Process count are slow-changing
    # reference numbers that don't deserve hero-row weight. Match the
    # Battery panel's pattern: one dim line with severity colour kept
    # on the load_1 value (the only one that meaningfully spikes).
    cores = sys_stats.cpu_count_logical or 1
    load_1 = sys_stats.load_1
    if load_1 >= 2 * cores:
        load_color = "bold red"
    elif load_1 >= cores:
        load_color = "yellow"
    else:
        load_color = "green"
    foot_parts = [
        f"[dim]load[/] [{load_color}]{load_1:.2f}[/] "
        f"[dim]/ {sys_stats.load_5:.2f} / {sys_stats.load_15:.2f}[/]",
    ]
    if sys_stats.topology:
        foot_parts.append(f"[dim]{sys_stats.topology}[/]")
    foot_parts.append(f"[dim]up {human_duration(sys_stats.uptime)}[/]")
    foot_parts.append(f"[dim]{sys_stats.total_processes} procs[/]")
    rows.append(("", "  ".join(foot_parts)))
    return _kv(rows)


def _cpu_panel(sys_stats: sys_mod.SystemStats) -> Panel:
    return Panel(
        cpu_content(sys_stats),
        title=Text.from_markup(cpu_title_summary(sys_stats)),
        box=SIMPLE,
        border_style="blue",
    )


_MEM_SEGMENTS: tuple[tuple[str, str], ...] = (
    # (attr-name-or-derived, colour) — order matters for visual stacking
    # in the composition bar: pinned/hard memory on the left, recoverable
    # on the right. Mirrors Activity Monitor / Stats.app's layout so
    # users transferring from those tools read it the same way.
    ("wired",      "bright_red"),
    ("compressed", "bright_yellow"),
    ("active",     "cyan"),
    ("free",       "dim white"),
)


def _memory_composition(mem: mem_mod.MemoryStats, *, width: int = 24) -> tuple[str, str]:
    """Return ``(bar_markup, legend_markup)`` for a segmented memory bar.

    The bar splits ``mem.total`` into four colour-coded segments —
    Wired (pinned) · Compressed (under pressure) · Active (other used)
    · Free (recoverable). Block counts use largest-remainder rounding
    so segments always sum to exactly ``width`` blocks regardless of
    fractional shares. Legend echoes each segment's colour with a small
    ■ swatch + byte value so the bar's colour code is self-documenting.
    """
    total = mem.total or 1
    wired = mem.wired
    compressed = mem.compressed
    # On macOS, ``used`` and ``compressed`` are reported as overlapping
    # categories — vm_stat counts compressed pages in a separate pool
    # from active/wired, but psutil's ``used`` derives from
    # ``total - available`` without subtracting compressed. So:
    #   * active = used minus wired (the "regular in-use" pages)
    #   * compressed is its own segment (not subtracted from active)
    #   * free is whatever's left after all three
    # Free is clamped so the four segments always sum to exactly total
    # — losing a couple hundred MB of slop is fine; the visual is
    # showing proportions, not exact bytes.
    active = max(0, mem.used - wired)
    free = max(0, total - wired - active - compressed)
    sizes = {"wired": wired, "compressed": compressed, "active": active, "free": free}

    raw = [sizes[name] / total * width for name, _ in _MEM_SEGMENTS]
    floors = [int(r) for r in raw]
    remaining = width - sum(floors)
    # Largest-remainder method: hand spare blocks to whichever segment
    # was rounded down most aggressively. Keeps segments visible even
    # when one is tiny relative to total RAM.
    order = sorted(range(len(raw)), key=lambda i: -(raw[i] - floors[i]))
    for i in order[:remaining]:
        floors[i] += 1

    bar_parts: list[str] = []
    for (_, color), n in zip(_MEM_SEGMENTS, floors, strict=True):
        if n > 0:
            bar_parts.append(f"[{color}]{'█' * n}[/]")
    bar_str = "".join(bar_parts) or f"[dim]{'░' * width}[/]"

    legend_parts: list[str] = []
    for (name, color), n in zip(_MEM_SEGMENTS, floors, strict=True):
        # Hide segments that rounded to zero blocks — surfacing a "0B"
        # swatch in the legend just adds noise when there's nothing to
        # see in the bar itself.
        if n == 0 and sizes[name] == 0:
            continue
        swatch_style = color if n > 0 else "dim"
        label_style = "dim" if name == "free" else color
        legend_parts.append(
            f"[{swatch_style}]■[/] [{label_style}]{name}[/] "
            f"[dim]{human_bytes(sizes[name])}[/]"
        )
    legend_str = "  ".join(legend_parts)
    return bar_str, legend_str


def mem_content(
    mem: mem_mod.MemoryStats,
    *,
    history: list[float] | None = None,
) -> Table:
    swap_pct = (mem.swap_used / mem.swap_total * 100.0) if mem.swap_total else 0.0
    swap_color = _pct_color(swap_pct)

    bar_str, legend_str = _memory_composition(mem)
    # The headline %% lives in the panel's border title (round 14)
    # now — no need to repeat it in the body. Bar still encodes %
    # visually; bytes + history sparkline tell the rest of the story.
    headline = (
        f"{bar_str}  "
        f"[dim]{human_bytes(mem.used)} / {human_bytes(mem.total)}[/]"
    )
    if history:
        # Severity-coloured history — same visual language as the CPU
        # panel so stress patterns read consistently across panels.
        headline += f"  {heatbar(history, hi=100.0, width=20)}"

    # Pressure level intentionally NOT a body row — the panel's
    # border title (mem_title_summary) already surfaces it as
    # "Memory · ● 74.3% · critical" so duplicating it in the body
    # was just two-times noise. Same fact, half the visual weight.
    rows: list[tuple[str, str]] = [
        ("Used", headline),
        # Legend sits on its own row with an empty label so it visually
        # belongs to the bar above it (Stats.app uses the same
        # "swatches under the bar" pattern).
        ("", legend_str),
        (
            "Swap",
            f"[{swap_color}]{bar(swap_pct, width=12)} {swap_pct:5.1f}%[/]  "
            f"[dim]{human_bytes(mem.swap_used)} / {human_bytes(mem.swap_total)}[/]"
            if mem.swap_total
            else "[dim]unused[/]",
        ),
    ]
    return _kv(rows)


def _mem_panel(mem: mem_mod.MemoryStats) -> Panel:
    return Panel(
        mem_content(mem),
        title=Text.from_markup(mem_title_summary(mem)),
        box=SIMPLE,
        border_style="magenta",
    )


def thermal_content(t: therm_mod.ThermalStats) -> Table:
    """Thermal / power summary, clustered into three semantic rows.

    Earlier versions rendered each pmset/SMC field on its own row,
    which made the panel scream "three red things!" whenever sleep
    was prevented — but display-sleep / disk-sleep / sleep-state are
    one problem, not three. Grouping by what the user actually cares
    about (thermal headroom · power source · sleep behaviour) cuts the
    panel to three rows and matches how Activity Monitor's Energy tab
    presents the same info.

    Single-colour glyphs only (kind-table calm-color rule): the dot
    carries severity, the label text stays neutral so the panel reads
    like a status card instead of a wall of coloured text.
    """
    def _chip(glyph: str, color: str, text: str) -> str:
        # Glyph carries severity colour; text stays neutral so a row
        # with three chips doesn't read like three competing alarms.
        return f"[{color}]{glyph}[/] {text}"

    OK, WARN, CRIT, IDLE = ("●", "green"), ("◆", "yellow"), ("▲", "bold red"), ("○", "dim")

    # ── Thermal row ── headroom, throttling, low-power mode all chip
    # together because they describe the same axis: "is the CPU free
    # to run at full clock?"
    if t.thermal_warning == "none":
        thermal_chip = _chip(*OK, "no warning")
    else:
        thermal_chip = _chip(*CRIT, f"warning {t.thermal_warning}")

    cpu_status = (t.cpu_power_status or "").lower()
    if "throttled" in cpu_status:
        cpu_chip = _chip(*CRIT, f"CPU {t.cpu_power_status}")
    elif cpu_status == "normal":
        cpu_chip = _chip(*OK, "CPU normal")
    else:
        cpu_chip = _chip(*IDLE, f"CPU {t.cpu_power_status or '?'}")

    lowpower_chip = (
        _chip(*WARN, "low-power on") if t.low_power_mode
        else _chip(*OK, "low-power off")
    )

    # ── Power row ── AC vs battery + percentage. Single chip because
    # there is only one axis here.
    pct = f" {t.battery_percent}%" if t.battery_percent is not None else ""
    if t.ac_power:
        power_chip = _chip(*OK, f"AC{pct}")
    elif t.battery_percent is not None and t.battery_percent < 20:
        power_chip = _chip(*WARN, f"battery{pct}")
    else:
        power_chip = _chip(*IDLE, f"battery{pct}")

    # ── Sleep row ── lead with the conclusion (prevented/allowed),
    # then dim-inline the timeout details so the symptom is still
    # surfaceable without three duplicate red rows.
    def _sleep_label(minutes: int | None) -> str:
        if minutes is None:
            return "?"
        if minutes == 0:
            return "never"
        return f"{minutes}m"

    sleep_lead = _chip(*CRIT, "prevented") if t.sleep_prevented else _chip(*OK, "allowed")
    sleep_detail = (
        f"[dim]display {_sleep_label(t.display_sleep)} · "
        f"disk {_sleep_label(t.disk_sleep)}[/]"
    )

    rows = [
        ("Thermal", f"{thermal_chip}  {cpu_chip}  {lowpower_chip}"),
        ("Power",   power_chip),
        ("Sleep",   f"{sleep_lead}  {sleep_detail}"),
    ]
    return _kv(rows)


def _thermal_panel(t: therm_mod.ThermalStats) -> Panel:
    return Panel(
        thermal_content(t),
        title=Text.from_markup(thermal_title_summary(t)),
        box=SIMPLE,
        border_style="red",
    )


def battery_content(b: batt_mod.BatteryStats | None) -> Table:
    """Battery cell details — capacity, cycles, temp, charge state.

    Temperature belongs on the *first line* here rather than in Thermal
    because cell temperature is what actually wears the battery out and is
    what users on 'cool-down-my-mac' typically care about when the laptop
    gets hot.
    """
    if b is None:
        # Empty state: desktop Macs (Mac mini / Studio / Pro) and Macs
        # plugged into a Studio Display have no battery. Surface that
        # explicitly so the otherwise-blank panel doesn't look broken.
        return _kv(
            [
                ("○", "[dim]no battery detected[/]"),
                ("", "[dim italic]desktop or display-only setup[/]"),
            ]
        )

    # Two-tier layout (iStat Menus / iPhone Settings pattern):
    #   * Hero rows — Level + Temp. These are the at-a-glance answers.
    #   * Footer strip — Health · Cycles · Flow · time-remaining. These
    #     change slowly or not at all per tick, so they recede to a
    #     single dim line that the user reads once and moves on.
    rows: list[tuple[str, str]] = []

    if b.percent is not None:
        color = "green" if b.percent >= 40 else "yellow" if b.percent >= 15 else "bold red"
        pct_cell = f"[{color}]{bar(b.percent)} {b.percent:5.1f}%[/]"
        if b.fully_charged:
            pct_cell += "  [dim green]charged[/]"
        elif b.charging:
            pct_cell += "  [dim green]charging[/]"
        elif b.ac_attached:
            pct_cell += "  [dim]on AC[/]"
        else:
            pct_cell += "  [dim yellow]on battery[/]"
        rows.append(("Level", pct_cell))

    if b.temp_c is not None:
        # Temp deserves the same visual weight as Level here because
        # battery cell temperature is the headline signal this whole
        # tool exists to surface. Add a 12-block thermometer bar with
        # the same colour scale used elsewhere (green / yellow / red),
        # mapped against a 50°C top (40°C ≈ 80% of the bar — hot).
        temp_color = (
            "bold red" if b.temp_c >= 40 else "yellow" if b.temp_c >= 35 else "green"
        )
        temp_pct = max(0.0, min(100.0, (b.temp_c / 50.0) * 100.0))
        rows.append(
            (
                "Temp",
                f"[{temp_color}]{bar(temp_pct, width=12)} {b.temp_c:.1f}°C[/]",
            )
        )

    # Footer strip — combine Health, Cycles, charge flow, and
    # time-remaining into a single dim line. Severity colours still
    # apply to the individual values so a degraded battery (low
    # health, high cycles) is still findable, but the surrounding
    # labels are dim so the row reads as quiet reference info.
    foot_parts: list[str] = []
    if b.health_percent is not None:
        h = b.health_percent
        h_color = "green" if h >= 85 else "yellow" if h >= 70 else "bold red"
        foot_parts.append(f"[dim]health[/] [{h_color}]{h:.1f}%[/]")
    if b.cycle_count is not None:
        # Apple rates most batteries for 1000 cycles — warn past 800.
        c_color = "green" if b.cycle_count < 600 else "yellow" if b.cycle_count < 900 else "bold red"
        foot_parts.append(f"[dim]cycles[/] [{c_color}]{b.cycle_count}[/]")
    if b.power_w is not None and abs(b.power_w) > 0.05:
        sign = "+" if b.charging and b.power_w > 0 else ""
        foot_parts.append(f"[dim]{sign}{b.power_w:.1f}W[/]")
    if b.minutes_remaining is not None:
        h, m = divmod(b.minutes_remaining, 60)
        rem = f"{h}h{m:02d}m" if h else f"{m}m"
        foot_parts.append(f"[dim]{rem} left[/]")
    if foot_parts:
        rows.append(("", "  ".join(foot_parts)))

    return _kv(rows)


def _battery_panel(b: batt_mod.BatteryStats | None) -> Panel:
    return Panel(
        battery_content(b),
        title=Text.from_markup(battery_title_summary(b)),
        box=SIMPLE,
        border_style="green",
    )


def _cli_panel(procs: list[procs_mod.ProcInfo]) -> Panel:
    groups = procs_mod.group_by_kind(procs)
    if not groups:
        return Panel(
            Text("no AI CLIs / multiplexers detected", style="dim"),
            title="[bold]AI CLI Inventory[/]",
            box=SIMPLE,
            border_style="yellow",
        )

    table = Table(box=None, expand=True, show_edge=False)
    table.add_column("kind", style="bold")
    table.add_column("count", justify="right")
    table.add_column("total RSS", justify="right")
    table.add_column("total CPU%", justify="right")
    table.add_column("idle (max)", justify="right")

    grand_total_procs = 0
    grand_total_rss = 0
    for kind, items in groups.items():
        total_rss = sum(p.rss for p in items)
        total_cpu = sum(p.cpu_percent for p in items)
        max_idle = max((p.idle_seconds or 0.0) for p in items)
        # Use the same per-family palette `cool watch` uses so a user
        # bouncing between the two views never sees claude rendered in
        # two different colours.
        color = kind_color(kind)
        idle_clr = idle_color(max_idle)
        # Colour lives on the family dot only; kind name stays bold
        # neutral. Same rule as `cool watch` — keeps a 6-kind inventory
        # legible instead of looking like confetti.
        # Idle duration gets severity colour so long-idle (= reapable)
        # rows surface visibly without reading numbers.
        table.add_row(
            f"[{color}]●[/] [bold]{kind}[/]",
            str(len(items)),
            human_bytes(total_rss),
            f"{total_cpu:.1f}",
            f"[{idle_clr}]{human_duration(max_idle)}[/]",
        )
        grand_total_procs += len(items)
        grand_total_rss += total_rss
    # Mirror `cool watch`'s pattern: surface the fleet aggregates in the
    # panel title so the user doesn't need to scan + sum the rows to
    # answer "how heavy is my AI CLI fleet right now?".
    title = (
        f"[bold]AI CLI Inventory[/]  [dim]· {grand_total_procs} procs · "
        f"{human_bytes(grand_total_rss)}[/]"
    )
    return Panel(table, title=title, box=SIMPLE, border_style="yellow")


def _compact_path(path: str, *, home: str) -> str:
    """Collapse ``$HOME`` to ``~`` so paths stay informative but shorter.

    Why not strip to basename like the old implementation: when three
    different `python script.py` invocations show up in the Hot Processes
    panel, basename-only renders them as identical rows. Keeping the
    project segments is what makes them distinguishable.
    """
    if home and (path == home or path.startswith(home + "/")):
        return "~" + path[len(home):]
    return path


def _shorten_path_token(path: str, max_len: int) -> str:
    """Compress one path token by dropping leading segments.

    ``/a/b/c/d/e/f.py`` with budget 12 → ``…/e/f.py``. Never strips
    fewer than the last two segments, so the script's parent directory
    (which usually identifies the project) survives even under pressure.
    """
    if len(path) <= max_len:
        return path
    segs = path.split("/")
    if len(segs) <= 2:
        return path  # nothing to compress (e.g. "script.py")
    # Walk from the tail outward, growing the kept suffix until it would
    # overflow. Always keep at least the last 2 segments.
    keep = 2
    while keep < len(segs):
        candidate = "…/" + "/".join(segs[-keep:])
        if len(candidate) > max_len:
            keep -= 1
            break
        keep += 1
    keep = max(keep, 2)
    return "…/" + "/".join(segs[-keep:])


def shorten_cmd(name: str, cmdline: str, width: int = 56) -> str:
    """Render a command line that stays informative under tight column budgets.

    Two design rules:
      1. Preserve the script-path *tail* — `python foo/script.py` and
         `python bar/script.py` must look different in the table.
      2. Drop only the interpreter prefix (the part before the first
         space) down to its basename — that's the part that's reliably
         long and uninformative (`/opt/homebrew/Cellar/python@3.14/.../Python`).

    Falls back to ``name`` when cmdline parsing leaves nothing useful.
    """
    parts = cmdline.split()
    if not parts:
        return name or "?"
    head = parts[0].rsplit("/", 1)[-1] or parts[0]

    home = os.environ.get("HOME", "")
    rest_parts: list[str] = []
    for tok in parts[1:]:
        if tok.startswith("/"):
            tok = _compact_path(tok, home=home)
        rest_parts.append(tok)
    rest = " ".join(rest_parts)
    shown = f"{head} {rest}".strip() if rest else head

    if len(shown) <= width:
        return shown

    # Over budget. The user picks rows by reading the *script* identity,
    # so spend the budget on the tail end of the first absolute-ish path
    # we find rather than truncating the whole string from the right
    # (which would chop the script name and leave only `Python`).
    target_idx: int | None = None
    for i, tok in enumerate(rest_parts):
        if "/" in tok:
            target_idx = i
            break
    if target_idx is not None:
        # Budget for the long path = total budget minus everything else.
        other_len = (
            len(head)
            + (1 if rest_parts else 0)
            + sum(len(t) + 1 for j, t in enumerate(rest_parts) if j != target_idx)
        )
        path_budget = max(8, width - other_len)
        rest_parts[target_idx] = _shorten_path_token(rest_parts[target_idx], path_budget)
        rest = " ".join(rest_parts)
        shown = f"{head} {rest}".strip() if rest else head

    if len(shown) > width:
        shown = shown[: width - 1] + "…"
    return shown


def hot_apps_content(apps: list[hot_mod.HotApp]) -> Table:
    """Render the Hot-by-app table. Public so callers/tests can reuse it.

    Leads with ``cores`` ("how many cores is this app eating") because the
    old normalized share reads as "5.6" for a process pinning a full core on
    an 18-core box — right, but uselessly small. ``%sys`` keeps that
    normalized share so the row still reconciles with the CPU panel total.
    """
    table = Table(box=None, expand=True, show_edge=False)
    table.add_column("app")
    table.add_column("cores", justify="right")
    table.add_column("%sys", justify="right")
    table.add_column("procs", justify="right", style="dim")
    table.add_column("rss", justify="right")
    # "note" carries only the leftover flag, so it stays short and the table
    # reads one line per app. The app name + cores/procs already say what an
    # ordinary group is; a hottest-member command path here just wrapped.
    table.add_column("note")

    if not apps:
        table.add_row("", "—", "—", "—", "—", "[dim]nothing burning CPU right now[/]")
        return table

    for a in apps:
        if a.cores >= 0.8:
            clr = "bold red"
        elif a.cores >= 0.4:
            clr = "yellow"
        else:
            clr = "green"
        name = f"[yellow]⚠[/] {a.app}" if a.origin else a.app
        note = (
            f"[yellow]{a.origin.tool} leftover · {a.origin.reason}[/]" if a.origin else ""
        )
        table.add_row(
            name,
            f"[{clr}]{a.cores:.1f}[/]",
            f"{a.pct_sys:.1f}%",
            str(a.nproc),
            human_bytes(a.rss),
            note,
        )
    return table


def _hot_procs_panel(
    apps: list[hot_mod.HotApp],
    cov: hot_mod.Coverage | None,
    sys_stats: sys_mod.SystemStats,
) -> Panel:
    # Title carries the coverage reconciliation so the user can tell the
    # panel is honest — "shown 73%" against an 88%-busy box means a chunk
    # of load lives in the hidden tail, not that nothing is wrong. The list
    # is already sorted by load (row 1 = hottest), so no separate "top:"
    # summary is needed; orphan leftovers are flagged on their own rows.
    syspct = sys_stats.cpu_percent
    shown = cov.shown_pct_sys if cov else 0.0
    tail = cov.tail_pct_sys if cov else 0.0
    tail_n = cov.tail_nproc if cov else 0
    title = (
        f"[bold]Hot Processes by CPU%[/]  [dim]· {syspct:.0f}% busy · "
        f"shown {shown:.0f}% · +{tail_n} more {tail:.0f}%[/]"
    )
    return Panel(hot_apps_content(apps), title=title, box=SIMPLE, border_style="red")


def health_score(
    mem: mem_mod.MemoryStats,
    sys_stats: sys_mod.SystemStats,
    t: therm_mod.ThermalStats,
    battery: batt_mod.BatteryStats | None = None,
) -> tuple[int, str]:
    score = 100
    # macOS reports a kernel-level memory pressure_level that is the
    # ground truth — it incorporates compression and page-in rate, both
    # of which can be high even when used_percent looks "fine" (e.g.
    # 76% used but 36% of RAM is compressed → kernel says critical).
    # Prefer it when available; fall back to raw used_percent only when
    # the kernel signal is missing.
    if mem.pressure_level == "critical":
        score -= 25
    elif mem.pressure_level == "warn":
        score -= 12
    elif mem.pressure_level not in ("normal", "warn", "critical"):
        if mem.used_percent >= 90:
            score -= 25
        elif mem.used_percent >= 80:
            score -= 12
    if mem.swap_total and mem.swap_used / mem.swap_total > 0.5:
        score -= 15
    if sys_stats.cpu_percent >= 80:
        score -= 15
    elif sys_stats.cpu_percent >= 60:
        score -= 6
    if t.thermal_warning != "none":
        score -= 20
    if t.sleep_prevented and t.display_sleep == 0:
        score -= 5
    # Battery cell temperature is THE signal this tool exists to surface
    # — without it the headline Health score can stay at 100 while the
    # laptop is too hot to hold. Use thresholds that match the colour
    # scale on the Battery panel (35°C warn / 40°C hot / 45°C critical).
    if battery is not None and battery.temp_c is not None:
        if battery.temp_c >= 45:
            score -= 20
        elif battery.temp_c >= 40:
            score -= 10
        elif battery.temp_c >= 35:
            score -= 3
    score = max(0, min(100, score))
    # Return base colour names (no bold prefix); callers can compose
    # ``[bold {color}]`` themselves. This avoids the "bold bold red"
    # marker that pops up when the colour is wrapped at the call site.
    if score >= 80:
        color = "green"
    elif score >= 55:
        color = "yellow"
    else:
        color = "red"
    return score, color


def render(console: Console | None = None) -> None:
    console = console or Console()
    with console.status("[dim]sampling...[/]", spinner="dots"):
        sys_stats = sys_mod.collect()
        mem = mem_mod.collect()
        therm = therm_mod.collect()
        procs = procs_mod.collect()
        procs_mod.enrich_idle(procs)
        hot_apps, hot_cov = hot_mod.aggregate_by_app(
            hot_mod.collect(),
            sys_stats.cpu_count_logical,
            top_n=20,
            key_fn=leftovers_mod.browser_aware_key,
        )
        leftovers_mod.annotate_origins(hot_apps)
        # Battery temperature is one of the headline cooldown signals; the
        # collector returns None on desktop Macs (Mac mini / Studio / Pro),
        # in which case the panel renders an explicit "no battery" empty
        # state instead of being omitted entirely.
        try:
            batt = batt_mod.collect()
        except Exception:  # noqa: BLE001
            batt = None

    score, score_color = health_score(mem, sys_stats, therm, batt)
    header_bits = [
        "[bold]cooldown[/] status",
        f"Health [bold {score_color}]● {score}[/]",
        f"[dim]{platform.node()}[/] · {platform.machine()} · macOS {platform.mac_ver()[0]}",
    ]
    console.print(Text("  ").join(Text.from_markup(b) for b in header_bits))
    console.print()

    # Two layouts depending on terminal width:
    #   ≥ 120 cols → 4-up column row matching `cool watch`'s top half
    #   < 120 cols → vertical stack so each panel keeps a readable width
    panels = [
        _cpu_panel(sys_stats),
        _mem_panel(mem),
        _thermal_panel(therm),
        _battery_panel(batt),
    ]
    if console.size.width >= 120:
        console.print(Columns(panels, equal=True, expand=True))
    else:
        for panel in panels:
            console.print(panel)
    console.print(_cli_panel(procs))
    console.print(_hot_procs_panel(hot_apps, hot_cov, sys_stats))
    console.print(_dev_panel())

    # Actionable advice block. Print every hint that applies, in
    # descending severity, so a user with three simultaneous problems
    # sees all three (the previous if/elif chain hid everything past the
    # first match).
    hints: list[str] = []
    if mem.pressure_level == "critical" or (
        mem.swap_total and mem.swap_used / mem.swap_total > 0.7
    ):
        hints.append(
            "[bold red]![/] memory pressure critical — run "
            "[cyan]cool procs[/] or [cyan]cool reap[/] to recover"
        )
    if therm.thermal_warning and therm.thermal_warning != "none":
        hints.append(
            f"[bold red]![/] thermal warning [bold red]{therm.thermal_warning}[/] — "
            "close GUI hogs with [cyan]cool apps suspend[/] or quit heavy AI CLIs"
        )
    if therm.sleep_prevented:
        hints.append(
            "[yellow]![/] sleep is being prevented — run "
            "[cyan]cool thermal --restore[/] to reset displaysleep / disksleep"
        )
    if batt is not None and batt.temp_c is not None and batt.temp_c >= 40:
        hints.append(
            f"[yellow]![/] battery cell hot ({batt.temp_c:.1f}°C) — "
            "give the laptop a few minutes off charge / heavy load"
        )
    if any(
        p.kind in procs_mod.AI_KINDS and (p.idle_seconds or 0) > 1800 for p in procs
    ):
        hints.append(
            "[yellow]hint:[/] idle AI CLI sessions detected — try "
            "[cyan]cool reap --dry-run[/]"
        )
    for hint in hints:
        console.print(hint)


def _as_jsonable(obj: Any) -> Any:
    """Recursively convert dataclasses + Paths into JSON-friendly forms."""
    if is_dataclass(obj) and not isinstance(obj, type):
        return {k: _as_jsonable(v) for k, v in asdict(obj).items()}
    if isinstance(obj, dict):
        return {k: _as_jsonable(v) for k, v in obj.items()}
    if isinstance(obj, list | tuple):
        return [_as_jsonable(v) for v in obj]
    if hasattr(obj, "__fspath__"):  # pathlib.Path
        return str(obj)
    return obj


def render_json(console: Console | None = None) -> None:
    """Machine-readable equivalent of ``render()`` for scripting."""
    console = console or Console()
    sys_stats = sys_mod.collect()
    mem = mem_mod.collect()
    therm = therm_mod.collect()
    procs = procs_mod.collect()
    procs_mod.enrich_idle(procs)
    hot = hot_mod.collect(top_n=5)
    try:
        batt = batt_mod.collect()
    except Exception:  # noqa: BLE001
        batt = None
    score, _ = health_score(mem, sys_stats, therm, batt)
    payload = {
        "health_score": score,
        "host": {
            "node": platform.node(),
            "machine": platform.machine(),
            "macos": platform.mac_ver()[0],
        },
        "system": _as_jsonable(sys_stats),
        "memory": _as_jsonable(mem),
        "thermal": _as_jsonable(therm),
        "battery": _as_jsonable(batt) if batt is not None else None,
        "procs": [_as_jsonable(p) for p in procs],
        "hot_procs": [_as_jsonable(h) for h in hot],
    }
    console.print_json(json.dumps(payload, default=str))


def render_group(mem: mem_mod.MemoryStats, sys_stats: sys_mod.SystemStats) -> Group:
    """Expose a Group for reuse (e.g., future `cool watch`)."""
    return Group(_cpu_panel(sys_stats), _mem_panel(mem))


def _dev_panel(limit: int = 5) -> Panel:
    """Top projects by RSS. Imported lazily so `cool status` still runs if
    the dev collector is missing or fails."""
    try:
        from ..collectors import dev as dev_mod  # noqa: PLC0415
        devs = dev_mod.collect(sample_interval=0.1)
    except Exception:  # noqa: BLE001
        return Panel(
            Text("dev collector unavailable", style="dim"),
            title="[bold]Top Projects by RSS[/]",
            box=SIMPLE,
            border_style="cyan",
        )

    groups = dev_mod.group_by(devs, "project")
    if not groups:
        return Panel(
            Text("no dev processes detected", style="dim"),
            title="[bold]Top Projects by RSS[/]",
            box=SIMPLE,
            border_style="cyan",
        )

    table = Table(box=None, expand=True, show_edge=False)
    # No fixed style on the "project" column — the cell markup from
    # decorate_project_name() already carries the right colour (bold for
    # real projects, dim-by-category for synthetic buckets).
    table.add_column("project")
    table.add_column("count", justify="right")
    table.add_column("total RSS", justify="right")
    # langs/launchers use chip_tokens() for per-token colour, so the
    # column-level dim style is dropped — chip colours win and dim
    # noise tokens are already individually dimmed inside chip_tokens.
    table.add_column("langs")
    table.add_column("launchers")

    ranked = sorted(
        groups.items(),
        key=lambda kv: -sum(d.rss for d in kv[1]),
    )[:limit]
    shown_total_rss = 0
    for name, items in ranked:
        total_rss = sum(d.rss for d in items)
        langs = ",".join(sorted({d.lang for d in items}))
        launchers = ",".join(sorted({d.launcher.kind for d in items}))
        orphan = any(d.is_orphan for d in items)
        # Use the same bucket-icon + truncation as `cool watch` so the
        # one-shot status view matches the live dashboard exactly.
        name_cell = decorate_project_name(name, orphan=orphan)
        table.add_row(
            name_cell,
            str(len(items)),
            human_bytes(total_rss),
            chip_tokens(langs),
            chip_tokens(launchers),
        )
        shown_total_rss += total_rss
    title = (
        f"[bold]Top Projects by RSS[/]  [dim]· {len(ranked)} shown · "
        f"{human_bytes(shown_total_rss)}[/]"
    )
    return Panel(table, title=title, box=SIMPLE, border_style="cyan")

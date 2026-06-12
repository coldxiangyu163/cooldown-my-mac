# cooldown-my-mac

**English** · [中文](./README.md)

<p align="center">
  <img src="./docs/images/cool-watch.png" alt="cool watch dashboard" width="100%">
</p>

<p align="center">
  <b>A cooldown CLI for the AI vibe-coding era</b><br>
  You thought you were just chatting with AI. Your Mac is being roasted by 100+ runaway node processes.
</p>

<p align="center">
  <a href="https://pypi.org/project/cooldown-my-mac/"><img alt="PyPI" src="https://img.shields.io/pypi/v/cooldown-my-mac.svg"></a>
  <img alt="Python" src="https://img.shields.io/badge/python-3.11%2B-blue">
  <img alt="Platform" src="https://img.shields.io/badge/platform-macOS-black">
  <img alt="Tests" src="https://img.shields.io/badge/tests-passing-brightgreen">
  <img alt="License" src="https://img.shields.io/badge/license-MIT-green">
</p>

---

## Why is your Mac hot again?

In the AI vibe-coding era, the culprit changed:

- 🥵 **"I was just chatting with Claude / Cursor"** — and the fans have been on full blast all day. Usually it's the MCP server that didn't exit when the session did.
- 🧠 **Memory pressure red, Activity Monitor is wall-to-wall `node`** — 5 AI CLIs each spawn their own copy of chrome-devtools-mcp / sequential-thinking / filesystem MCP. 100+ node procs, 4 GB+ gone.
- 👻 **You quit Cursor / Codex / Droid, but CPU is still pegged** — child processes didn't follow the parent down. The orphans were adopted by launchd and forgotten forever.
- 🌳 **That `next dev` / `vite` the AI spun up months ago is still running** — you've long forgotten about it. It hasn't forgotten about your RAM.
- 🚀 **Every reboot brings back another wave of LaunchAgents** — Cursor / Claude Desktop / Codex / Raycast / messaging apps all want to live in the tray.

`cool` is a macOS CLI built for AI vibe coders: it attributes every process across three axes — **project / AI CLI / launcher** — so you know which of those 100 node procs belong to what, and can reap them by family. Comes with memory-pressure guarding, a 24/7 launchd-managed daemon, and a JSONL audit log.

It does **not replace** [Mole](https://github.com/tw93/Mole) (disk cleanup) / [mactop](https://github.com/context-labs/mactop) (hardware readings) / [stats](https://github.com/exelban/stats) (menu bar). It fills the gap they leave in the AI era: **the runaway dev processes that your AI agents leave behind.**

## Highlights

**AI CLI family awareness** *(built for vibe coding)*
- Built-in recognition for droid · codex · claude · opencode · cursor-agent · aider · hermes · cmux · gemini-cli ... aggregated for display, reaped per family
- Auto-detects MCP servers (chrome-devtools-mcp / sequential-thinking / filesystem / any npx package) so they don't pollute your real project stats
- Every dev process tagged with `project root + launcher + lang/framework`; a 7-level fallback chain guarantees coverage (`cwd unknown` never shows up)

**CPU runaway visibility**
- `Hot Processes by CPU%` panel **aggregates current CPU by owning app** (cores / %sys / proc count), **regardless of AI family** — MCP child scripts, Chrome renderers, third-party GUIs all surface here; leaked automation browsers (agent-browser / puppeteer / playwright) are flagged with a ⚠
- Anything at ≥ 80% of a single core is painted bold red, so a runaway PID is visible at a glance
- Shared between `cool status` and `cool watch`; press `k` to kill the PID you just visually picked

**Hardware awareness**
- Battery: `ioreg` for cell temp / cycles / health
- SMC: CPU/GPU temps + CPU throttle state
- Apple Silicon: P-cores and E-cores get separate avg + max bars

**Automation & guarding**
- Memory pressure *critical* triggers auto `sudo purge` + reap + macOS notification
- Auto-cleans orphaned automation browsers leaked by agent-browser / puppeteer / playwright (whole Chrome subtree; daemon rule is off by default, reaps only the old-and-quiet, spares active sessions)
- 24/7 launchd daemon + YAML rule engine; install is idempotent
- One-shot fix for displaysleep / disksleep / sleep-prevention

**Safety & auditability**
- `--dry-run` on every destructive operation
- JSONL oplog at `~/Library/Logs/cooldown/`
- Self-protection chain + Apple-agent refusal
- Default `SIGTERM` + 3 s grace + `SIGKILL`

**Script-friendly**
- `status / procs / dev / ports / thermal` all support `--json` for `jq` pipelines

## Here's the culprit

Real `cool dev` output on a Mac with a few AI CLIs left running — you'll realise you have no idea where most of these came from:

```text
PROJECT                                 #      RSS  LANGS     LAUNCHERS
────────────────────────────────────────────────────────────────────────────────
(npx: chrome-devtools-mcp)            102    4.1GB  node      claude,codex,droid
search-boss                            31    1.5GB  node      cmux,codex,launchd,vscode
(app: Visual Studio Code)              16    1.3GB  node      vscode
(npx: @modelcontextprotocol/serve...   31    1.2GB  node      claude,codex,droid
(npx: mcp-server-sequential-think...   31    925MB  node      claude,codex,droid
music-train-ios                        14    679MB  node      codex,launchd
```

**Translation**: claude / codex / droid each spawned their own chrome-devtools-mcp — 102 node procs, 4.1 GB total. *This* is why your Mac sounds like a jet engine when you're "just chatting with AI." The real project `search-boss` is held simultaneously by cmux + codex + launchd + vscode, meaning at least three AI sessions have touched it. Pick a slice, reap the family in one keystroke.

## Install

```bash
pipx install cooldown-my-mac
pipx inject cooldown-my-mac textual   # optional: enables the `cool watch` TUI
```

Requires Python 3.11+ (tested on 3.13 / 3.14). Registers two entry points: `cool` (short) and `cooldown` (long).

<details>
<summary>From source (for local development)</summary>

```bash
git clone https://github.com/coldxiangyu163/cooldown-my-mac.git
cd cooldown-my-mac
uv sync --extra watch --extra dev
uv run cool status
```

</details>

## Quick start

By use case:

| You want to... | Run |
|---|---|
| Don't know where to start — pop the interactive menu | `cool` |
| See overall Mac health (CPU / mem / temp / AI CLI count) | `cool status` |
| Open the full-screen live dashboard | `cool watch` |
| **CPU is on fire — pinpoint which PID** | `cool status` or `cool watch`, read the Hot Processes panel |
| Find which AI CLI session is hogging the most | `cool procs` |
| Reap every AI CLI idle ≥ 30 min (incl. their MCP children) | `cool reap` |
| See which project each dev proc belongs to — and which AI spawned it | `cool dev` |
| Figure out which port Cursor / Claude is holding | `cool ports 5432` |
| Auto-reap + purge when memory pressure spikes | `cool pressure --watch --auto-reap --auto-purge --yes` |
| 24/7 background guardian (for when you forget to quit AI) | `cool daemon install` |
| Pipe machine-readable output | `cool status --json \| jq` |

## Commands

Every command takes `--help` for its full flag set. The most common invocations:

**Live dashboard `cool watch`** — dual-tempo refresh: fast tick (3 s) samples CPU/Memory/Thermal/Battery/AI CLI/Hot Processes; slow tick (15 s) samples Top Projects/Ports. Screenshot at [top](#cooldown-my-mac).

```text
┌─ Health · Model · Chip · RAM/Disk · macOS · uptime · batt temp · pressure · ⟳ 3s/15s ─┐
├──────────────────────────────────┬──────────────────────────────────┤
│  CPU                             │  Memory                          │  fast (3 s)
│  P-cores / E-cores avg + max     │  used / avail · swap · pressure  │
├──────────────────────────────────┼──────────────────────────────────┤
│  Thermal                         │  Battery                         │  fast (3 s)
│  warnings · throttle · fans      │  % · temp · cycles · health      │
├──────────────────────────────────┼──────────────────────────────────┤
│  AI CLI Inventory                │  Top Projects by RSS             │  slow (15 s)
│  kind · count · rss · idle       │  project · # · rss · launchers   │
├──────────────────────────────────┼──────────────────────────────────┤
│  Hot Processes by CPU% (by app)  │  Listening Ports                 │  fast / slow
│  app · cores · %sys · rss · note │  port · pid · process · launcher │
└──────────────────────────────────┴──────────────────────────────────┘
```

<details>
<summary>cool watch key bindings</summary>

| Key | Action |
|-----|--------|
| `q` | Quit |
| `r` / `R` | Force fast / slow refresh |
| `p` | Pause / resume |
| `d` | Toggle dry-run |
| `k` / `K` | `SIGTERM` / `SIGKILL` selected row |
| `1` / `2` / `3` / `4` | Focus AI CLI / Top Projects / Ports / Hot Processes |
| `+` / `-` | Fast-tick interval ±1 s |
| `[` / `]` | Slow-tick interval ±5 s |
| `Tab` / arrows | Navigate within a table |

</details>

**Dev-stack insight `cool dev` · `cool ports`**
```bash
cool dev                          # group by project: RSS / CPU / idle / launcher
cool dev --by launcher --stale    # orphans + stale projects, by launcher; --kill for interactive
cool ports 5432                   # who owns :5432? --free 4000:4100 lists free slots
```

**Process reaping `cool procs` · `cool reap`** — self-protection + SIGTERM/3s/SIGKILL + [oplog](#how-it-works)
```bash
cool procs                        # list every AI CLI / multiplexer, multi-select kill
cool reap --dry-run               # preview reapable AI CLI / tmux idle ≥ 30 min
cool reap --kinds droid,claude --yes        # narrow to families, skip confirm
cool reap --leftovers --dry-run   # preview leaked automation browsers (agent-browser/puppeteer/playwright); kill tears down the whole Chrome subtree
```

**Memory pressure `cool pressure`**
```bash
cool pressure --watch -n 60                                     # poll every 60 s
cool pressure --watch --auto-reap --auto-purge --notify --yes   # 24 h guardian combo
```

**Services & apps `cool services` · `cool apps`**
```bash
cool services stop mysql postgres -y                  # batch-stop dev services
cool apps suspend --kind wechat --kind dingtalk -y    # IM SIGSTOP (keeps state, stops CPU)
cool apps resume --kind wechat -y                     # SIGCONT
```

**Thermal / launchd / daemon `cool thermal` · `cool launchd` · `cool daemon`**
```bash
cool thermal --restore            # reset displaysleep / disksleep / powernap defaults
cool launchd --audit --disable    # list third-party agents + interactive bootout (Apple refused)
cool daemon config-init           # write ~/.config/cooldown/daemon.yaml (incl. the leftovers auto-reap rule, off by default)
cool daemon install               # register the 24/7 LaunchAgent
```

<details>
<summary>Sample YAML rule config (<code>~/.config/cooldown/config.yaml</code>)</summary>

```yaml
tick_interval_seconds: 120
rules:
  - name: reap-idle-ai-when-warm
    if:
      mem_pressure: [warn, critical]
      ai_idle_minutes: 30
    do:
      - reap_idle_ai
  - name: purge-on-critical
    if:
      mem_pressure: [critical]
    do:
      - purge_system
      - notify: "Memory critical — purged system caches"
```

</details>

## Menu bar app (Coolant)

When you don't want to open a terminal, `cool` now has a face too — a native SwiftUI menu bar app, **Coolant** (under [`menubar/`](./menubar/)).

- **Glanceable**: a snowflake plus CPU/battery temperature in the menu bar. While healthy it stays a quiet monochrome template icon; it only takes on color (red) when something is actually wrong — thermal warning, critical memory pressure, a core on fire.
- **A frosted-glass instrument cluster on click**: a hero status card (AI process count + memory footprint, with a gradient that tracks the health band), health/CPU/memory/battery chips, tappable diagnosis badges (runaway CPU / reapable sessions / memory pressure — each one tap from its fix), a per-core load chart, AI-CLI family and per-project rankings, and a hot-process list. One-tap reap idle AI / purge / open `cool watch`, with every destructive action behind a confirm chip. Fully light/dark adaptive; the last sample is cached to disk so the popover opens instantly.
- **Same source of truth**: the bar only draws; every reading is shelled out from `cool ... --json`, so colors and thresholds always match `cool watch`.

```bash
cd menubar && APP_NAME=Cooldown ./build-app.sh && open dist/Cooldown.app
```

Requires macOS 14+ and an installed `cool` (`pipx install cooldown-my-mac`). See [`menubar/README.md`](./menubar/README.md) and [`docs/menubar-design-spec.md`](./docs/menubar-design-spec.md) for the design and full notes.

## How it works

Two internals people often ask about — expand to read:

<details>
<summary>Attribution pipeline: a 7-step chain so <code>Top Projects</code> never shows <code>cwd unknown</code></summary>

```
┌──────────────────────────────────────────────────────────────────┐
│  1. npx cache / npm exec / bare MCP tool name → (npx: <pkg>)     │
│     prevents MCP helpers spawned by claude/droid from polluting  │
│     whichever project's cwd they inherited                       │
├──────────────────────────────────────────────────────────────────┤
│  2. find_root(cwd) — walk up cwd looking for 15 markers (.git,   │
│     package.json, pyproject.toml, go.mod, Cargo.toml, …). When   │
│     a monorepo subdir (apps/web, packages/ui) is hit, walk one  │
│     level up to land on the workspace root.                      │
├──────────────────────────────────────────────────────────────────┤
│  3. _synthesize_app_project — cmdline or cwd traversing an X.app │
│     bundle → (app: X). Covers Electron helpers.                  │
├──────────────────────────────────────────────────────────────────┤
│  4. _synthesize_vscode_ext_project — .vscode/extensions/<pub>.   │
│     <name>-<ver> → (vscode: name)                                │
├──────────────────────────────────────────────────────────────────┤
│  5. _synthesize_cmdline_project — parse --dir / --cwd / --prefix │
├──────────────────────────────────────────────────────────────────┤
│  6. _synthesize_cwd_project — parse the cwd *string* even when   │
│     the directory has been deleted (long-running dev server      │
│     outliving its git clone)                                     │
├──────────────────────────────────────────────────────────────────┤
│  7. _bucket_orphan_project — ppid=1 at cwd=/ → (orphan)          │
├──────────────────────────────────────────────────────────────────┤
│  Final fallback → (background: <argv0>), bucket by executable    │
└──────────────────────────────────────────────────────────────────┘
```

Launcher detection walks the `ppid` chain for tmux · cmux · vscode · claude · droid · codex · aider · launchd and 10+ other session types.

</details>

<details>
<summary>Safety internals: oplog, self-protection chain, Apple-agent refusal</summary>

Highlights lists the four headline safety guarantees. The extras worth knowing:

- **oplog path**: `~/Library/Logs/cooldown/operations.log` — one JSONL line per kill / suspend / bootout. Set `COOL_NO_OPLOG=1` to disable.
- **Apple-agent refusal pattern**: `cool launchd` refuses anything matching `com.apple.*` or `gui/501/com.apple.*`.
- **Self-protection mechanics**: `_self_pid_chain` walks the invoking process up via `ppid` to init; nothing on the chain can be reaped or suspended.
- **Idempotent daemon install** — safe to re-run; never double-registers.

</details>

## FAQ

**Q: Will it kill a session I'm actively using?**  
A: No. `reap` only touches processes with `idle_seconds >= 1800` (30 min of tty inactivity); your live Claude / Codex / Cursor session won't be touched. The self-protection chain also excludes cool itself and all its ancestors. Run `--dry-run` first if you want a list before the kill.

**Q: Why are there still node procs running after I quit Claude / Cursor?**  
A: It's a common side effect of the MCP architecture — each AI CLI spawns MCP servers over stdio, and many servers don't implement graceful shutdown, so the children get reparented to launchd as orphans when the parent dies. `cool dev --stale` and `cool reap` exist precisely for this case.

**Q: `sudo purge` — any side effects?**  
A: `purge` is a first-party macOS command that drops the inactive filesystem cache. The only "side effect" is a few seconds of slightly slower disk reads until the cache repopulates.

**Q: Does it work on Intel Macs?**  
A: Yes. Topology displays as "NP+0E" (Intel has no E-cores). The battery parser includes Intel's deci-Kelvin decoder. Thermal / battery data are richer on Apple Silicon.

## Roadmap

- [ ] Network panel (up/down sparklines)
- [ ] Disk Trash / big-file locator
- [ ] Richer rule-engine DSL (compound conditions, cooldown periods)
- [ ] Group-kill in `cool dev --kill` (whole project / whole launcher)

<details>
<summary>How cooldown divides labour with other Mac tools</summary>

`cooldown-my-mac` **does not compete with these — use them together**:

| Tool | What it does | Division of labour |
|------|-------|--------------|
| [Mole](https://github.com/tw93/Mole) | Disk cleanup / one-shot tune-up | Mole owns disk, cooldown owns processes |
| [mactop](https://github.com/context-labs/mactop) · [macmon](https://github.com/vladkens/macmon) | Apple Silicon hardware readings (GPU / ANE / power) | They surface hardware; cooldown surfaces userland attribution |
| [stats](https://github.com/exelban/stats) | Menu-bar long-running readings | Stats for passive glancing, cooldown for "why is my Mac hot *right now*" |
| [btop++](https://github.com/aristocratos/btop) · htop | Generic process monitors | btop is generic, cooldown is Mac + AI-CLI opinionated |
| Activity Monitor | macOS built-in | The CLI cousin with project attribution and batch operations |

</details>

## Contributing

Issues and PRs welcome. Local development:

```bash
.venv/bin/pip install -e ".[watch,dev]"
.venv/bin/python -m pytest tests/ -q       # all green
.venv/bin/python -m ruff check cooldown tests
```

Code style: Ruff (lint + format) + type hints. New collectors / UIs should come with regression tests.

## License

MIT © coldxiangyu

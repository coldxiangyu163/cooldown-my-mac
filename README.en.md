# cooldown-my-mac

**English** · [中文](./README.md)

<p align="center">
  <img src="./docs/images/cool-watch.png" alt="cool watch dashboard" width="100%">
</p>

<p align="center">
  <b>A runtime thermal &amp; workload manager for heavy Mac users</b><br>
  Tames the pile of AI CLIs (droid · codex · claude · cursor-agent ...) you keep running 24/7,<br>
  reaping idle sessions <em>before</em> they overheat your Mac.
</p>

<p align="center">
  <a href="https://pypi.org/project/cooldown-my-mac/"><img alt="PyPI" src="https://img.shields.io/pypi/v/cooldown-my-mac.svg"></a>
  <img alt="Python" src="https://img.shields.io/badge/python-3.11%2B-blue">
  <img alt="Platform" src="https://img.shields.io/badge/platform-macOS-black">
  <img alt="Tests" src="https://img.shields.io/badge/tests-passing-brightgreen">
  <img alt="License" src="https://img.shields.io/badge/license-MIT-green">
</p>

---

[Why this exists](#why-this-exists) ·
[Highlights](#highlights) ·
[Install](#install) ·
[Quick start](#quick-start) ·
[Commands](#commands) ·
[`cool watch` anatomy](#cool-watch-anatomy) ·
[Attribution pipeline](#attribution-pipeline) ·
[Safety model](#safety-model) ·
[Vs. similar tools](#vs-similar-tools) ·
[FAQ](#faq) ·
[Roadmap](#roadmap)

## Why this exists

macOS already has [Mole](https://github.com/tw93/Mole) (disk), [mactop](https://github.com/context-labs/mactop) / [macmon](https://github.com/vladkens/macmon) (hardware), and [stats](https://github.com/exelban/stats) (menu bar) — but **none of them understand your dev workload**. When you have 3 droid sessions + 2 claude-code + 5 `next dev` + 10 IDE language-servers + a pile of forgotten mysql/postgres daemons, you need a tool that **attributes every process to its project / AI CLI / launcher and lets you cull idle sessions in one keystroke**.

## Highlights

| | Capability | One-liner |
|---|---|---|
| 🎯 | **Process attribution** | Every dev proc is tagged with project root + launcher + lang/framework; 7-level fallback chain guarantees coverage |
| 🧠 | **AI CLI family awareness** | droid · codex · claude · opencode · cursor-agent · aider · hermes · ... aggregated and reaped by family |
| 🔥 | **Battery + SMC depth** | `ioreg` for cell temp / cycles / health; SMC for CPU/GPU temps + throttling state |
| 📊 | **P/E-core split CPU** | Apple Silicon P-cores and E-cores get separate avg + max bars |
| 🚦 | **Memory-pressure guard** | Auto `sudo purge` + reap + macOS notification when *critical*; can run headless in watch mode |
| 🌙 | **Sleep-policy repair** | One command restores displaysleep / disksleep / clears sleep-prevention |
| 🛡️ | **launchd audit** | Enumerates third-party agents; hardcoded-refuses `com.apple.*` |
| ⚙️ | **24/7 rule engine** | YAML rules under launchd; idempotent install |
| 📝 | **Fully auditable** | JSONL oplog · `--dry-run` everywhere · self-protection · SIGTERM + 3s + SIGKILL |
| 🔌 | **Script-friendly** | `status / procs / dev / ports / thermal` all support `--json` for `jq` pipelines |

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
python3 -m venv .venv
.venv/bin/pip install -e ".[watch,dev]"
echo "alias cool='$(pwd)/.venv/bin/cool'" >> ~/.zshrc && source ~/.zshrc
```

</details>

## Quick start

```bash
cool                              # Mole-style interactive menu
cool status                       # one-shot health snapshot
cool watch                        # full-screen live dashboard (screenshot above)
```

By use case:

| You want to... | Run |
|---|---|
| See overall Mac health | `cool status` |
| Find the heaviest AI CLI sessions | `cool procs` |
| Reap every AI CLI idle ≥ 30 min | `cool reap` |
| See which project each dev proc belongs to | `cool dev` |
| Find out who owns port 5432 | `cool ports 5432` |
| Auto-reap on memory pressure | `cool pressure --watch --auto-reap --auto-purge --yes` |
| 24/7 background guardian | `cool daemon install` |
| Pipe machine-readable output | `cool status --json \| jq` |

For example — what `cool dev` actually shows on a Mac with a few AI CLIs running:

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

At a glance: three AI CLIs (claude / codex / droid) each spawned chrome-devtools-mcp, totalling 102 node procs and 4.1 GB; the real project `search-boss` is held simultaneously by cmux + codex + launchd + vscode. Which slice to cull, which to keep — immediately obvious.

## Commands

### Dev-stack insight — `cool dev` · `cool ports`

```bash
cool dev                          # group by project (default); shows RSS / CPU / idle / launcher
cool dev --by launcher            # tmux=12 droid=8 vscode=6 ...
cool dev --stale                  # orphans + projects with root mtime > 7d
cool dev --kill                   # interactive multi-select kill

cool ports                        # all listening ports with pid / project / launcher
cool ports 5432                   # who owns :5432?
cool ports --free 4000:4100       # which ports are free in this range
```

<details>
<summary>More flags (group by lang/framework, filter by project, port conflicts...)</summary>

```bash
cool dev --by lang                # node=34 python=12 ruby=3 go=2
cool dev --by framework           # next=6 uvicorn=3 rails=1 ...
cool dev --project macool         # filter to one project
cool dev --lang python            # python family only
cool dev --json                   # structured output for piping

cool ports 4000:5000              # port range
cool ports --conflict             # same port held by multiple pids
cool ports --kill                 # pick ports → kill their holders
```

</details>

### Process reaping — `cool procs` · `cool reap`

```bash
cool procs                        # list every AI CLI / multiplexer; multi-select kill
cool reap                         # reap every AI CLI / tmux session idle ≥ 30 min
cool reap --dry-run               # preview what would be killed
cool reap --kinds droid,claude --yes        # narrow to specific families, skip confirm
```

Triple safety: ① self-protection chain excludes cool and every ancestor ② `SIGTERM` + 3 s grace + `SIGKILL` ③ all actions logged to [oplog](#safety-model).

### Memory pressure — `cool pressure`

```bash
cool pressure                                         # one-shot: normal / warn / critical
cool pressure --watch -n 60                           # every 60 s indefinitely
cool pressure --watch --auto-reap --auto-purge --notify --yes   # 24 h guardian combo
```

### Services & apps — `cool services` · `cool apps`

```bash
cool services                     # toggle: mysql / postgres / redis / elasticsearch / nanobot / hermes
cool services stop mysql postgres -y

cool apps list                    # show RSS for common hogs: wechat / dingtalk / feishu / lark / qq / teams / slack / zoom
cool apps suspend --kind wechat --kind dingtalk -y    # SIGSTOP (keeps state, stops CPU)
cool apps resume --kind wechat -y                     # SIGCONT
```

### Thermal & launchd — `cool thermal` · `cool launchd`

```bash
cool thermal                      # temps / throttling / fans / pmset policy
cool thermal --restore            # reset displaysleep=10, disksleep=10, unblock sleep

cool launchd                      # list every user LaunchAgent (sorted by RSS)
cool launchd --audit --disable    # interactive bootout picker (Apple agents refused)
```

### Background daemon — `cool daemon`

```bash
cool daemon config-init           # write default ~/.config/cooldown/config.yaml
cool daemon install               # register the LaunchAgent
cool daemon status                # running? last tick? log path?
cool daemon logs                  # tail the runner log
cool daemon uninstall             # bootout + delete plist
```

<details>
<summary>Sample YAML rule config</summary>

`~/.config/cooldown/config.yaml`:

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

## `cool watch` anatomy

4 rows × 2 cols, Ports spans the bottom (screenshot at the [top](#cooldown-my-mac)):

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
├──────────────────────────────────┴──────────────────────────────────┤
│  Listening Ports                                                    │  slow (15 s)
│  port · proto · pid · process · project · launcher                  │
└─────────────────────────────────────────────────────────────────────┘
```

**Dual-tempo refresh**: fast tick (3 s) samples CPU / Memory / Thermal / Battery / AI CLI; slow tick (15 s) samples Top Projects / Ports. Each collector runs in its own worker, so a single failure only paints one panel red.

<details>
<summary>Key bindings</summary>

| Key | Action |
|-----|--------|
| `q` | Quit |
| `r` / `R` | Force fast / slow refresh |
| `p` | Pause / resume |
| `d` | Toggle dry-run |
| `k` / `K` | `SIGTERM` / `SIGKILL` selected row |
| `1` / `2` / `3` | Focus AI CLI / Top Projects / Ports |
| `+` / `-` | Fast-tick interval ±1 s |
| `[` / `]` | Slow-tick interval ±5 s |
| `Tab` / arrows | Navigate within a table |

</details>

## Attribution pipeline

Most process monitors can tell you "a lot of node is running" but can't say "for what". `cooldown-my-mac` runs every dev process through a strict-to-weak 7-step chain — the `Top Projects` panel **never shows `(cwd unknown)`**.

<details>
<summary>Expand: 7-step attribution chain (first hit wins)</summary>

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

## Safety model

- **`--dry-run` everywhere** that could kill / suspend / bootout.
- **Self-protection**: `cool reap` / `cool apps` build `_self_pid_chain` from the invoking process upward and exclude it so you can't accidentally kill your own shell.
- **Apple-owned agents are hardcoded-refused** in `cool launchd`.
- **oplog** at `~/Library/Logs/cooldown/operations.log` (JSONL). Set `COOL_NO_OPLOG=1` to disable.
- **SIGTERM + 3s grace window + SIGKILL** by default.
- **Idempotent daemon install** — safe to re-run.

## Vs. similar tools

`cooldown-my-mac` **does not compete with these — use them together**:

| Tool | What it does | Division of labour |
|------|-------|--------------|
| [Mole](https://github.com/tw93/Mole) | Disk cleanup / one-shot tune-up | Mole owns disk, cooldown owns processes |
| [mactop](https://github.com/context-labs/mactop) · [macmon](https://github.com/vladkens/macmon) | Apple Silicon hardware readings (GPU / ANE / power) | They surface hardware; cooldown surfaces userland attribution |
| [stats](https://github.com/exelban/stats) | Menu-bar long-running readings | Stats for passive glancing, cooldown for "why is my Mac hot *right now*" |
| [btop++](https://github.com/aristocratos/btop) · htop | Generic process monitors | btop is generic, cooldown is Mac + AI-CLI opinionated |
| Activity Monitor | macOS built-in | The CLI cousin with project attribution and batch operations |

## FAQ

**Q: Will it kill a session I'm actively using?**  
A: No. `reap` only touches processes with `idle_seconds >= 1800` (30 min of tty inactivity). The self-protection chain excludes cool itself and all its ancestors. Run `--dry-run` if you're not sure.

**Q: `sudo purge` — any side effects?**  
A: `purge` is a first-party macOS command that drops the inactive filesystem cache. The only "side effect" is a few seconds of slightly slower disk reads until the cache repopulates.

**Q: What are the `(npx: chrome-devtools-mcp)` entries in Top Projects?**  
A: MCP tools one of your AI CLIs (droid / claude / cursor-agent) has spawned. They live in `~/.npm/_npx/` and can be safely killed — the AI CLI will respawn them on next use.

**Q: Does it work on Intel Macs?**  
A: Yes. Topology displays as "NP+0E" (Intel has no E-cores). The battery parser includes Intel's deci-Kelvin decoder. Thermal / battery data are richer on Apple Silicon.

## Roadmap

Not yet:

- [ ] Network panel (up/down sparklines)
- [ ] Disk Trash / big-file locator
- [ ] Richer rule-engine DSL (compound conditions, cooldown periods)
- [ ] Group-kill in `cool dev --kill` (whole project / whole launcher)

<details>
<summary>Shipped (12 commands)</summary>

`cool status` · `cool watch` · `cool dev` · `cool ports` · `cool procs` · `cool reap` · `cool pressure` · `cool services` · `cool apps` · `cool thermal` · `cool launchd` · `cool daemon`

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

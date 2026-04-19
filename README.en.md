# cooldown-my-mac

**English** · [中文](./README.md)

<p align="center">
  <img src="./docs/images/cool-watch.png" alt="cool watch dashboard" width="100%">
</p>

<p align="center">
  <b>A runtime thermal &amp; workload manager for heavy Mac users</b><br>
  Tames the pile of AI CLIs (droid · codex · claude · opencode · cursor-agent ...) you keep running 24/7,<br>
  reaping idle sessions, orphan processes, and ballooning MCP helpers <em>before</em> they overheat your Mac.
</p>

<p align="center">
  <a href="https://pypi.org/project/cooldown-my-mac/"><img alt="PyPI" src="https://img.shields.io/pypi/v/cooldown-my-mac.svg"></a>
  <img alt="Python" src="https://img.shields.io/badge/python-3.11%2B-blue">
  <img alt="Platform" src="https://img.shields.io/badge/platform-macOS-black">
  <img alt="Tests" src="https://img.shields.io/badge/tests-212%20passing-brightgreen">
  <img alt="License" src="https://img.shields.io/badge/license-MIT-green">
</p>

---

## Why this exists

macOS already has great "static" tools:
- [Mole](https://github.com/tw93/Mole) — disk cleanup, one-shot optimisation
- [mactop](https://github.com/context-labs/mactop) / [macmon](https://github.com/vladkens/macmon) / `mo status` — system dashboards
- [stats](https://github.com/exelban/stats) — menu-bar readings

**None of them understand your actual dev workload.** When you have:
- 3 droid sessions, 2 claude-code, 1 codex, each dragging a bag of MCP helpers
- 5 `next dev` / `vite` / `uvicorn` processes spawned from tmux/cmux
- 10 VS Code / Cursor language-server helpers
- A pile of forgotten `mysql` / `postgres` / `redis` / `nanobot` daemons

...what you need is not yet another CPU bar chart. You need a tool that **attributes every process to its project / AI CLI / launcher, and lets you cull idle sessions in one keystroke**. That's what `cooldown-my-mac` does.

## Headline features

| Capability | How |
|------------|-----|
| 🎯 **Process attribution** | Every node / python / ruby is attributed to: a `project root` (walking up cwd for `.git` / `package.json` / `pyproject.toml` + 12 more markers), a `launcher` (tmux / cmux / vscode / claude / droid / codex / launchd), and a `language + framework` (next / vite / uvicorn / rails / cargo / ...). A 6-level fallback chain (npx / vscode-ext / app-bundle / stale-cwd / orphan / background) **guarantees the Top Projects panel never shows `(cwd unknown)`**. |
| 🧠 **AI-CLI aware** | Recognises droid / codex / claude / opencode / cursor-agent / aider / crush / hermes / nanobot / cmux / tmux families. Aggregates count + RSS + max idle per kind, reaps whole families in one keypress. |
| 🔥 **Battery &amp; thermal depth** | The Battery panel parses `ioreg AppleSmartBattery`: percent · **cell temperature** · health · cycles · charge flow. Thermal reads `pmset -g therm` + SMC and surfaces CPU throttling state and sleep-policy sabotage. |
| 📊 **P/E-core split CPU** | Apple Silicon P-cores and E-cores get separate avg + max bars so you can tell a single-core bottleneck from a broad load. |
| 🚦 **Memory-pressure guard** | When `sysctl vm.memorystatus_level` says *critical*, cooldown can auto-`sudo purge`, reap idle AI CLIs, and throw a macOS notification. Can run headless in watch mode. |
| 🌙 **Sleep-policy repair** | One command restores `displaysleep=10` / `disksleep=10` / clears sleep-prevention after AI CLIs have sabotaged them. |
| 🛡️ **launchd audit** | Enumerates every third-party LaunchAgent / LaunchDaemon while refusing to touch anything Apple-owned. |
| ⚙️ **24/7 rule engine** | `cool daemon install` registers itself as a LaunchAgent that evaluates a YAML rule set (memory / AI idle / disk) on a cadence. Idempotent. |
| 📝 **Fully auditable** | Every kill / suspend / bootout writes `~/Library/Logs/cooldown/operations.log` as JSONL. Destructive actions always require confirm or `--yes`. Every command supports `--dry-run`. |

## Install

### Option 1: pipx (recommended)

```bash
pipx install cooldown-my-mac
pipx inject cooldown-my-mac textual   # optional: enables `cool watch` TUI
```

Registers two entry points: `cool` (short) and `cooldown` (long). Requires Python 3.11+ (tested on 3.13 / 3.14).

### Option 2: from source (recommended for local dev)

```bash
git clone https://github.com/coldxiangyu163/cooldown-my-mac.git
cd cooldown-my-mac
python3 -m venv .venv
.venv/bin/pip install -e ".[watch,dev]"

# Alias it so edits take effect without any reinstall step
echo "alias cool='$(pwd)/.venv/bin/cool'" >> ~/.zshrc
source ~/.zshrc
```

## Quick start

```bash
cool                              # Mole-style interactive menu, 19 choices
cool status                       # one-shot health snapshot (single screen)
cool watch                        # full-screen live dashboard (screenshot above)
cool menu                         # same as bare `cool`
```

I recommend `cool status` first, then follow its hints into `reap` / `pressure` / `services`.

## Commands in detail

### Dev-stack insight — `cool dev` / `cool ports`

```bash
# Who started these node/python procs? Which project? Which port?
cool dev                          # group by project (default). Shows RSS / CPU / idle / launcher.
cool dev --by launcher            # tmux=12 droid=8 vscode=6 cmux=4 launchd=9
cool dev --by lang                # node=34 python=12 ruby=3 go=2
cool dev --by framework           # next=6 uvicorn=3 rails=1 ...
cool dev --stale                  # orphans (ppid=launchd) + stale-project procs (root mtime > 7d)
cool dev --project macool         # filter to one project
cool dev --lang python            # python family only
cool dev --kill                   # multi-select interactive kill
cool dev --json                   # structured output for piping

# Port map: who owns :3000? is it conflicting with :3001?
cool ports                        # all listening ports (Apple system filtered out) with pid/project/launcher
cool ports 5432                   # who owns :5432?
cool ports 4000:5000              # port range
cool ports --conflict             # same port held by multiple pids
cool ports --free 4000:4100       # which ports are still free in this range
cool ports --kill                 # pick ports → kill their holders
```

### AI CLI / process reaping — `cool procs` / `cool reap`

```bash
cool procs                        # list every AI CLI / multiplexer; multi-select kill
cool reap                         # reap every droid/codex/claude/tmux session idle >= 30min
cool reap --dry-run               # preview what would be killed
cool reap --kind codex --ai-idle 1800
cool reap --kind tmux --tmux-no-clients      # tmux sessions with zero clients attached
cool reap --kinds droid,claude,codex --yes   # batch + skip confirm
```

Triple safety on `reap`: ① self-protection chain built from `_self_pid_chain` excludes cool and every ancestor ② default `SIGTERM` + 3-second grace window + `SIGKILL` ③ every action logged to oplog.

### Memory pressure — `cool pressure`

```bash
cool pressure                                         # one-shot: normal / warn / critical
cool pressure --watch -n 60                           # every 60s indefinitely
cool pressure --watch --notify                        # macOS notification on critical
cool pressure --auto-reap --auto-purge --yes          # auto reap AI + sudo purge on critical
cool pressure --watch -n 30 --auto-reap --auto-purge --notify --yes   # 24h guardian combo
```

### Local services / heavy GUI apps — `cool services` / `cool apps`

```bash
cool services                     # toggle: mysql / postgres / redis / elasticsearch / nanobot / hermes
cool services stop mysql postgres -y

cool apps list                    # show RSS for common hogs: wechat / dingtalk / feishu / lark / qq / teams / slack / zoom
cool apps suspend --kind wechat --kind dingtalk -y    # SIGSTOP (keeps state, stops CPU)
cool apps resume --kind wechat -y                     # SIGCONT
```

### Thermal / sleep / launchd

```bash
cool thermal                      # temps / throttling / fans / pmset policy
cool thermal --restore            # reset displaysleep=10, disksleep=10, unblock sleep

cool launchd                      # list every user LaunchAgent (sorted by RSS)
cool launchd --audit --disable    # interactive bootout picker (Apple agents refused)
```

### 24/7 rule engine — `cool daemon`

```bash
cool daemon config-init           # write default config to ~/.config/cooldown/config.yaml
cool daemon install               # register ~/Library/LaunchAgents/ai.cooldown.agent.plist
cool daemon status                # running? last tick? log path?
cool daemon logs                  # tail the runner log
cool daemon uninstall             # bootout + delete plist
```

Sample config (`~/.config/cooldown/config.yaml`):
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

## `cool watch` anatomy

<p align="center">
  <img src="./docs/images/cool-watch.png" alt="cool watch layout" width="100%">
</p>

**Layout** — 4 rows × 2 cols, Ports spans the bottom row:

| Row | Panel | Contents |
|-----|-------|----------|
| Top | Dense header | Health · Model · Chip · P/E topology · RAM/Disk · macOS · uptime · battery temp · memory pressure · AI CLI count · last op · tick cadence |
| 1 | CPU \| Memory | CPU split into P-cores / E-cores (avg + max) · Memory with swap / pressure |
| 2 | Thermal \| Battery | Thermal warnings / power mode / sleep policy · Percent / temp / health / cycles |
| 3 | AI CLI \| Top Projects | AI CLI families aggregated · Project-attributed RSS ranking |
| Bottom | Listening Ports (col-span 2) | port · pid · process · project · launcher |

**Keys**:

| Key | Action |
|-----|--------|
| `q` | Quit |
| `r` / `R` | Force fast / slow refresh |
| `p` | Pause/resume all ticks |
| `d` | Toggle dry-run (kill actions become no-ops) |
| `k` / `K` | `SIGTERM` / `SIGKILL` selected row |
| `1` / `2` / `3` | Focus AI CLI / Top Projects / Ports table |
| `+` / `-` | Fast-tick interval ±1s |
| `[` / `]` | Slow-tick interval ±5s |
| `Tab` / arrows | Navigate within a table |

**Dual-tempo refresh**: CPU / Memory / Thermal / Battery / AI CLI every 3s (fast), Top Projects / Ports every 15s (slow). Each collector runs in its own worker so a single failure only paints one panel red.

## Attribution pipeline (why Top Projects never shows `(cwd unknown)`)

This is the core technical differentiator. Most monitors can tell you "a lot of node is running" but can't say "for what". Our chain, in strict-to-weak order:

```
┌──────────────────────────────────────────────────────────────────┐
│  Every node/python/ruby/go/... proc walks this 7-step chain;     │
│  the first hit wins.                                             │
├──────────────────────────────────────────────────────────────────┤
│  1. npx cache / npm exec / bare MCP tool name → (npx: <pkg>)     │
│     prevents MCP helpers spawned by claude/droid from polluting  │
│     whichever project's cwd they inherited                       │
├──────────────────────────────────────────────────────────────────┤
│  2. find_root(cwd) — walk up cwd looking for any of 15 markers   │
│     (.git, package.json, pyproject.toml, go.mod, Cargo.toml, …). │
│     When a monorepo subdir (apps/web, packages/ui) is hit, walk  │
│     one more level up to land on the workspace root.             │
├──────────────────────────────────────────────────────────────────┤
│  3. _synthesize_app_project — cmdline or cwd traversing an X.app │
│     bundle → (app: X). Covers Electron helpers (VS Code /        │
│     Obsidian / Slack / WeChat).                                  │
├──────────────────────────────────────────────────────────────────┤
│  4. _synthesize_vscode_ext_project — .vscode/extensions/<pub>.   │
│     <name>-<ver> → (vscode: name)                                │
├──────────────────────────────────────────────────────────────────┤
│  5. _synthesize_cmdline_project — parse --dir / --cwd / --prefix │
│     CLI flags                                                    │
├──────────────────────────────────────────────────────────────────┤
│  6. _synthesize_cwd_project — parse the cwd *string* even when   │
│     the directory has been deleted (long-running dev server      │
│     outliving its git clone). Matches ~/personal/project/<X>,    │
│     ~/work/<X>, ~/code/<X>, ~/src/<X> anchors.                   │
├──────────────────────────────────────────────────────────────────┤
│  7. _bucket_orphan_project — ppid=1 at cwd=/ → (orphan)          │
├──────────────────────────────────────────────────────────────────┤
│  Final fallback → (background: <argv0>), bucket by executable    │
└──────────────────────────────────────────────────────────────────┘
```

Launcher detection walks the `ppid` chain for tmux / cmux / vscode / claude / droid / codex / aider / launchd and 10+ other session types.

## Safety model

- **`--dry-run` everywhere** that could kill / suspend / bootout.
- **Self-protection**: `cool reap` / `cool apps` build `_self_pid_chain` from the invoking process upward and exclude it so you can't accidentally kill your own shell.
- **Apple-owned agents are hardcoded-refused** in `cool launchd`.
- **oplog** at `~/Library/Logs/cooldown/operations.log` (JSONL). Set `COOL_NO_OPLOG=1` to disable.
- **SIGTERM + 3s grace window + SIGKILL** by default.
- **Idempotent daemon install** — safe to re-run.

## Vs. similar tools

| Tool | Focus | Relationship |
|------|-------|--------------|
| [Mole](https://github.com/tw93/Mole) | Disk cleanup + one-shot optimisation | **Complementary.** Mole owns disk, cooldown owns processes. Use together. |
| [mactop](https://github.com/context-labs/mactop) / [macmon](https://github.com/vladkens/macmon) | Apple Silicon hardware readings (GPU / ANE / power) | **Complementary.** They go deep into hardware, we go deep into userland attribution. |
| [stats](https://github.com/exelban/stats) | Menu bar long-running readings | **Complementary.** Stats for passive glancing, cooldown for "why is my Mac hot *right now*". |
| [btop++](https://github.com/aristocratos/btop) / htop | Generic process monitors | **Overlapping but differently scoped.** btop is generic, cooldown is Mac + AI-CLI opinionated. |
| Activity Monitor | macOS built-in | **cooldown is its command-line cousin with project attribution and batch operations.** |

## FAQ

**Q: Will it kill a session I'm actively using?**  
A: No. `reap` only touches processes with `idle_seconds >= 1800` (30 min of tty inactivity). The self-protection chain excludes cool itself and all its ancestors. Run `--dry-run` if you're not sure.

**Q: `sudo purge` — any side effects?**  
A: `purge` is a first-party macOS command that drops the inactive filesystem cache. The only "side effect" is a few seconds of slightly slower disk reads until the cache repopulates.

**Q: What are the `(npx: chrome-devtools-mcp)` entries in Top Projects?**  
A: MCP tools one of your AI CLIs (droid / claude / cursor-agent) has spawned. They live in `~/.npm/_npx/` and can be safely killed — the AI CLI will respawn them on next use.

**Q: Does it work on Intel Macs?**  
A: Yes. Topology displays as "NP+0E" (Intel has no E-cores). The battery parser includes Intel's deci-Kelvin temperature decoder. But thermal / battery are richer on Apple Silicon.

**Q: Why pipx and not pip?**  
A: pipx isolates cool into its own venv and symlinks the entry point into `~/.local/bin/`, keeping your system Python clean. If you're comfortable with venvs, pip works too.

## Roadmap

- [x] `cool status` — one-shot dashboard (+ Top Projects by RSS)
- [x] `cool watch` — full-screen Textual dashboard (P/E cores + Battery panel + 4×2 grid)
- [x] `cool dev` — dev-stack inventory + 7-level attribution
- [x] `cool ports` — listening-port map with pid / project / launcher
- [x] `cool procs` — AI CLI inventory + interactive kill
- [x] `cool reap` — idle-session reaper
- [x] `cool pressure` — memory-pressure guard
- [x] `cool services` — local service toggle
- [x] `cool apps` — IM / GUI suspend &amp; resume
- [x] `cool thermal` — thermal panel + sleep-policy repair
- [x] `cool launchd` — launchd audit + selective bootout
- [x] `cool daemon` — 24/7 rule engine (launchd-managed)
- [ ] Network panel (up/down sparklines)
- [ ] Disk Trash / big-file locator
- [ ] Richer rule-engine DSL (compound conditions, cooldown periods)
- [ ] Group-kill in `cool dev --kill` (whole project / whole launcher in one go)

## Contributing

Issues and PRs welcome. Local development:

```bash
.venv/bin/pip install -e ".[watch,dev]"
.venv/bin/python -m pytest tests/ -q       # 212 passing
.venv/bin/python -m ruff check cooldown tests
```

Code style: Ruff (lint + format) + type hints. New collectors / UIs should come with regression tests.

## License

MIT © coldxiangyu

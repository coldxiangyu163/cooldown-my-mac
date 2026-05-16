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

## What's happening to your Mac?

- Fans spinning all day, Activity Monitor can't tell you who's eating CPU
- Memory pressure red, but you don't know which forgotten `next dev` is holding 4 GB
- 5 AI CLIs each spawned their own copy of MCP tools — 100+ node processes total
- After a reboot, a pile of LaunchAgents / mysql / postgres comes back; nobody remembers why

`cool` is a macOS CLI that attributes every process across three axes — **project / AI CLI / launcher** — and gives you batch reaping, memory-pressure guarding, and a 24/7 launchd-managed daemon. It does **not replace** [Mole](https://github.com/tw93/Mole) (disk) / [mactop](https://github.com/context-labs/mactop) (hardware readings) / [stats](https://github.com/exelban/stats) (menu bar); it fills the gap they leave — your dev workload.

## Highlights

**Process attribution & identity**
- Every dev process tagged with `project root + launcher + lang/framework`; a 7-level fallback chain guarantees coverage (`cwd unknown` never shows up)
- AI CLI family awareness: droid · codex · claude · opencode · cursor-agent · aider · hermes ... aggregated for display, reaped per family

**Hardware awareness**
- Battery: `ioreg` for cell temp / cycles / health
- SMC: CPU/GPU temps + CPU throttle state
- Apple Silicon: P-cores and E-cores get separate avg + max bars

**Automation & guarding**
- Memory pressure *critical* triggers auto `sudo purge` + reap + macOS notification
- 24/7 launchd daemon + YAML rule engine; install is idempotent
- One-shot fix for displaysleep / disksleep / sleep-prevention

**Safety & auditability**
- `--dry-run` on every destructive operation
- JSONL oplog at `~/Library/Logs/cooldown/`
- Self-protection chain + Apple-agent refusal
- Default `SIGTERM` + 3 s grace + `SIGKILL`

**Script-friendly**
- `status / procs / dev / ports / thermal` all support `--json` for `jq` pipelines

## Sample output

`cool dev` on a typical Mac with a few AI CLIs running:

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

By use case:

| You want to... | Run |
|---|---|
| Pop up the interactive menu (Mole-style) | `cool` |
| See overall Mac health | `cool status` |
| Open the full-screen live dashboard | `cool watch` |
| Find the heaviest AI CLI sessions | `cool procs` |
| Reap every AI CLI idle ≥ 30 min | `cool reap` |
| See which project each dev proc belongs to | `cool dev` |
| Find out who owns port 5432 | `cool ports 5432` |
| Auto-reap on memory pressure | `cool pressure --watch --auto-reap --auto-purge --yes` |
| 24/7 background guardian | `cool daemon install` |
| Pipe machine-readable output | `cool status --json \| jq` |

## Commands

Every command takes `--help` for its full flag set. The most common invocations:

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
cool thermal --restore            # reset displaysleep / disksleep / unblock sleep
cool launchd --audit --disable    # list third-party agents + interactive bootout (Apple refused)
cool daemon install               # register the 24/7 LaunchAgent
```

**Live dashboard `cool watch`** — dual-tempo refresh: fast tick (3 s) samples CPU/Memory/Thermal/Battery/AI CLI; slow tick (15 s) samples Top Projects/Ports. Screenshot at [top](#cooldown-my-mac).

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

<details>
<summary>cool watch key bindings</summary>

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

## How it works

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
A: No. `reap` only touches processes with `idle_seconds >= 1800` (30 min of tty inactivity). The self-protection chain excludes cool itself and all its ancestors. Run `--dry-run` if you're not sure.

**Q: `sudo purge` — any side effects?**  
A: `purge` is a first-party macOS command that drops the inactive filesystem cache. The only "side effect" is a few seconds of slightly slower disk reads until the cache repopulates.

**Q: Does it work on Intel Macs?**  
A: Yes. Topology displays as "NP+0E" (Intel has no E-cores). The battery parser includes Intel's deci-Kelvin decoder. Thermal / battery data are richer on Apple Silicon.

## Roadmap

Not yet:

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

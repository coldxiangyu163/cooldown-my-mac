# cooldown-my-mac

Runtime thermal and workload manager for heavy Mac users who keep many AI CLIs
(droid, codex, claude, opencode, ...) running 24/7.

> Complements [Mole](https://github.com/tw93/Mole): Mole cleans the disk and
> runs one-shot optimizations; cooldown-my-mac watches the live workload and
> culls zombie agents, runs memory-pressure guards, tames sleep / thermal
> behavior, and can run 24/7 as a launchd agent.

## Install

```bash
pipx install cooldown-my-mac
# Optional full-screen TUI:
pipx inject cooldown-my-mac textual
```

Two entry points are registered: `cool` (short) and `cooldown` (long alias).

## Usage

```bash
cool                              # interactive menu (Mole-style)
cool status                       # one-shot health dashboard
cool watch                        # full-screen live dashboard (Textual)

# AI CLI / process management
cool procs                        # interactive multi-select kill
cool reap                         # reap idle droid/codex/claude/tmux sessions
cool reap --dry-run               # preview
cool reap --kind codex --ai-idle 1800

# Memory pressure
cool pressure                     # one-shot evaluation
cool pressure --watch -n 60 --notify
cool pressure --auto-reap --auto-purge --yes

# Local services + heavy apps
cool services                     # mysql/postgres/redis/nanobot/hermes toggle
cool apps list
cool apps suspend --kind wechat --kind dingtalk -y
cool apps resume --kind wechat -y

# Thermal + sleep policy + launchd audit
cool thermal
cool thermal --restore            # restore displaysleep/disksleep = 10
cool launchd                      # summary
cool launchd --audit --disable    # interactive bootout picker

# 24/7 background rule engine
cool daemon config-init
cool daemon install               # writes ~/Library/LaunchAgents/ai.cooldown.agent.plist
cool daemon status
cool daemon logs
cool daemon uninstall
```

Destructive actions always ask for confirmation. Operations are logged to
`~/Library/Logs/cooldown/operations.log` (disable with `COOL_NO_OPLOG=1`).

## Safety

- Every kill / suspend / disable has a `--dry-run` mode.
- `cool reap` and `cool apps` protect the calling process and all its ancestors.
- `cool launchd` refuses to disable any Apple-owned agent.
- `cool daemon` is idempotent; `install` is safe to run repeatedly.

## Roadmap

- [x] `cool status` — one-shot dashboard
- [x] `cool procs` — AI CLI inventory + interactive kill
- [x] `cool reap` — idle session reaper
- [x] `cool pressure` — memory-pressure guard (+ watch / auto-reap / auto-purge / notify)
- [x] `cool services` — local dev services toggle
- [x] `cool apps` — IM / GUI app suspend & resume
- [x] `cool thermal` — thermal dashboard + sleep policy restore
- [x] `cool launchd` — launchd audit & selective bootout
- [x] `cool daemon` — launchd-managed rule engine
- [x] `cool watch` — full-screen Textual live dashboard

## License

MIT

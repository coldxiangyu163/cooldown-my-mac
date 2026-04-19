# cooldown-my-mac

Runtime thermal and workload manager for heavy Mac users who keep many AI CLIs
(droid, codex, claude, opencode, ...) running 24/7.

> Complements [Mole](https://github.com/tw93/Mole): Mole cleans the disk and
> runs one-shot optimizations; cooldown-my-mac watches the live workload and
> culls zombie agents, runs memory-pressure guards, and tames sleep / thermal
> behavior.

## Install

```bash
pipx install cooldown-my-mac
```

Two entry points are registered: `cool` (short) and `cooldown` (long alias).

## Usage

```bash
cool                 # interactive menu (Mole-style)
cool status          # one-shot health dashboard
cool procs           # group AI CLI processes, multi-select to kill
cool reap            # cull idle droid/codex/claude/tmux sessions
cool reap --dry-run  # preview only
cool --help
```

Destructive actions always ask for confirmation. Operations are logged to
`~/Library/Logs/cooldown/operations.log` (disable with `COOL_NO_OPLOG=1`).

## Roadmap

- [x] `cool status` — live health dashboard
- [x] `cool procs` — AI CLI inventory + interactive kill
- [x] `cool reap` — idle session reaper
- [x] `cool pressure` — memory-pressure guard (+ `--watch`, `--auto-reap`, `--auto-purge`, `--notify`)
- [ ] `cool services` — mysql/postgres/redis/nanobot/hermes switch
- [ ] `cool apps` — SIGSTOP/SIGCONT throttling for WeChat/DingTalk/Lark
- [ ] `cool thermal` — SMC temps + sleep policy
- [ ] `cool launchd` — agent/daemon audit
- [ ] `cool daemon` — launchd-managed rule engine
- [ ] `cool watch` — Textual full-screen live view

## License

MIT

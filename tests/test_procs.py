from cooldown.collectors import procs as procs_mod
from cooldown.collectors.procs import ProcInfo


def test_classify():
    assert procs_mod._classify("droid", "/usr/local/bin/droid run") == "droid"
    assert procs_mod._classify("node", "/usr/bin/node codex-server") == "codex"
    assert procs_mod._classify("zsh", "/bin/zsh -l") is None
    assert procs_mod._classify("tmux", "tmux new -s work") == "tmux"
    assert procs_mod._classify("python3", "/usr/bin/python3 claude_cli.py") == "claude"


def test_classify_extended_ai_clis():
    # Gemini CLI (Google), bare invocation + npm-packaged variant.
    assert procs_mod._classify("gemini", "/opt/homebrew/bin/gemini --help") == "gemini"
    assert procs_mod._classify("node", "node /usr/local/lib/node_modules/@google/gemini-cli/bin/gemini") == "gemini"
    # Aider, run via the python launcher.
    assert procs_mod._classify("python", "/opt/homebrew/bin/aider --model gpt-4o") == "aider"
    assert procs_mod._classify("aider", "aider") == "aider"
    # Cursor Agent CLI (must outrank the generic Cursor IDE substring).
    assert procs_mod._classify("cursor-agent", "/Applications/Cursor.app/Contents/Resources/app/bin/cursor-agent") == "cursor-agent"
    # GitHub Copilot — both standalone CLI and VS Code extension host.
    assert procs_mod._classify("node", "node /Users/x/.vscode/extensions/github.copilot-1.0.0/dist/agent.js") == "copilot"
    assert procs_mod._classify("gh", "gh copilot suggest") == "copilot"
    # Windsurf / Qwen / Kimi / Goose / Aichat / Continue / Amp / Crush.
    assert procs_mod._classify("windsurf", "/Applications/Windsurf.app/Contents/MacOS/windsurf") == "windsurf"
    assert procs_mod._classify("node", "node /Users/x/.npm/@qwen-code/qwen-code/bin/qwen") == "qwen"
    assert procs_mod._classify("kimi", "/opt/homebrew/bin/kimi-cli --chat") == "kimi"
    assert procs_mod._classify("goose", "/usr/local/bin/goose session") == "goose"
    assert procs_mod._classify("aichat", "/usr/local/bin/aichat -s") == "aichat"
    assert procs_mod._classify("node", "node /Users/x/.continue/bin/continue") == "continue"
    assert procs_mod._classify("node", "node /usr/local/lib/node_modules/@sourcegraph/amp/bin/amp") == "amp"
    assert procs_mod._classify("node", "node /usr/local/lib/node_modules/@charm/crush/bin/crush") == "crush"


def test_classify_does_not_false_positive_on_common_paths():
    # "raider" must not match "aider", shared lib paths must not match
    # things like "gemini" or "copilot".
    assert procs_mod._classify("raider", "/Applications/raider.app/Contents/MacOS/raider") is None
    assert procs_mod._classify("ruby", "/usr/bin/ruby /path/to/my-aider-clone.rb") != "aider"  # no /aider & no ' aider '
    # A shell subshell shouldn't be mistaken for anything.
    assert procs_mod._classify("zsh", "zsh -i") is None


def _p(pid: int, kind: str, rss: int, idle: float | None = None, cpu: float = 0.0) -> ProcInfo:
    return ProcInfo(
        pid=pid,
        ppid=1,
        kind=kind,
        name=kind,
        cmdline=f"{kind} --run",
        rss=rss,
        cpu_percent=cpu,
        create_time=0.0,
        age=0.0,
        tty=None,
        user="me",
        idle_seconds=idle,
    )


def test_group_by_kind_sorted_by_total_rss():
    items = [
        _p(1, "droid", 100),
        _p(2, "droid", 200),
        _p(3, "codex", 500),
    ]
    grouped = procs_mod.group_by_kind(items)
    kinds = list(grouped.keys())
    assert kinds[0] == "codex"  # largest total first
    # Inside a group, sorted by -rss
    assert [p.pid for p in grouped["droid"]] == [2, 1]


def test_enrich_idle_uses_cpu_fallback():
    items = [_p(1, "droid", 100, cpu=0.0)]
    items[0].age = 300.0
    procs_mod.enrich_idle(items)
    assert items[0].idle_seconds is not None
    assert items[0].idle_seconds > 0

from cooldown.collectors import procs as procs_mod
from cooldown.collectors.procs import ProcInfo


def test_classify():
    assert procs_mod._classify("droid", "/usr/local/bin/droid run") == "droid"
    assert procs_mod._classify("node", "/usr/bin/node codex-server") == "codex"
    assert procs_mod._classify("zsh", "/bin/zsh -l") is None
    assert procs_mod._classify("tmux", "tmux new -s work") == "tmux"
    assert procs_mod._classify("python3", "/usr/bin/python3 claude_cli.py") == "claude"


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

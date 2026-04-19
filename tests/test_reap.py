import os

from cooldown.actions import reap as reap_act
from cooldown.collectors.procs import ProcInfo


def _mk(pid: int, kind: str = "droid") -> ProcInfo:
    return ProcInfo(
        pid=pid,
        ppid=1,
        kind=kind,
        name=kind,
        cmdline=f"{kind} run",
        rss=1,
        cpu_percent=0.0,
        create_time=0.0,
        age=0.0,
        tty=None,
        user="me",
        idle_seconds=9999.0,
    )


def test_dry_run_does_not_kill():
    results = reap_act.terminate([_mk(999999)], dry_run=True)
    assert len(results) == 1
    assert results[0].ok is True
    assert "dry-run" in results[0].message


def test_self_protection():
    me = os.getpid()
    results = reap_act.terminate([_mk(me)], dry_run=False)
    assert len(results) == 1
    assert results[0].ok is False
    assert "protected" in results[0].message


def test_nonexistent_pid_marked_gone():
    results = reap_act.terminate([_mk(999_999_999)], dry_run=False)
    assert results[0].ok is True
    assert "gone" in results[0].message

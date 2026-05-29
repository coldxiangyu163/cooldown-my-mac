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


# _descendants now returns (pid, name, exe, create_time) so the killer can
# vet each child is chromium and validate identity against PID reuse.
def _chrome_child(pid: int):
    return (pid, "Google Chrome Helper", "/Applications/Google Chrome.app/x", 0.0)


def test_automation_browser_expands_to_subtree(monkeypatch):
    """Reaping an automation browser tears down its whole helper fleet
    (renderer/gpu/utility), so the killer expands the target to its live
    subtree."""
    monkeypatch.setattr(
        reap_act,
        "_descendants",
        lambda pid: [_chrome_child(5001), _chrome_child(5002)] if pid == 5000 else [],
    )
    results = reap_act.terminate([_mk(5000, kind="automation-browser")], dry_run=True)
    assert {r.pid for r in results} == {5000, 5001, 5002}
    assert all("dry-run" in r.message for r in results)


def test_non_browser_target_is_not_expanded(monkeypatch):
    """A plain AI-CLI / mux target keeps single-process semantics; we never
    walk its subtree."""
    queried: list[int] = []
    monkeypatch.setattr(
        reap_act, "_descendants", lambda pid: queried.append(pid) or [_chrome_child(9)]
    )
    results = reap_act.terminate([_mk(123, kind="droid")], dry_run=True)
    assert queried == []
    assert {r.pid for r in results} == {123}


def test_subtree_never_includes_protected_self(monkeypatch):
    """Even if our own pid shows up as a descendant, self-protection keeps it
    out of the kill set."""
    me = os.getpid()
    monkeypatch.setattr(reap_act, "_descendants", lambda pid: [_chrome_child(me)])
    results = reap_act.terminate([_mk(7000, kind="automation-browser")], dry_run=True)
    assert me not in {r.pid for r in results}


def test_subtree_skips_non_chromium_descendant(monkeypatch):
    """Defense in depth: a process reparented under the browser root that is
    NOT itself chromium must never be swept into the kill set."""
    monkeypatch.setattr(
        reap_act,
        "_descendants",
        lambda pid: [
            _chrome_child(8001),
            (8002, "python3.13", "/usr/bin/python3.13", 0.0),  # unrelated
        ],
    )
    results = reap_act.terminate([_mk(8000, kind="automation-browser")], dry_run=True)
    assert {r.pid for r in results} == {8000, 8001}  # python child spared


def test_escalation_records_actual_sigkill_signal(monkeypatch):
    """When SIGTERM is ignored and we escalate to SIGKILL, the oplog audit must
    record SIGKILL — not the initial SIGTERM — or the trail lies about what
    actually killed the process. Uses a real process that ignores SIGTERM."""
    import subprocess
    import sys

    import psutil

    code = (
        "import signal,sys,time\n"
        "signal.signal(signal.SIGTERM, signal.SIG_IGN)\n"
        "sys.stdout.write('ready\\n'); sys.stdout.flush()\n"
        "time.sleep(30)\n"
    )
    proc = subprocess.Popen([sys.executable, "-c", code], stdout=subprocess.PIPE, text=True)
    try:
        assert proc.stdout is not None
        proc.stdout.readline()  # block until SIGTERM is actually being ignored
        ct = psutil.Process(proc.pid).create_time()
        target = ProcInfo(
            pid=proc.pid, ppid=1, kind="droid", name="x", cmdline="x run",
            rss=1, cpu_percent=0.0, create_time=ct, age=0.0, tty=None,
            user="me", idle_seconds=0.0,
        )
        recorded: list = []
        monkeypatch.setattr(reap_act, "record", lambda event, **kw: recorded.append((event, kw)))

        out = reap_act.terminate([target], dry_run=False, timeout=0.5)

        assert out[0].ok is True
        assert "SIGKILL" in out[0].message
        kill_rec = [kw for ev, kw in recorded if ev == "reap.kill"]
        assert kill_rec and kill_rec[0]["signal"] == "SIGKILL"
    finally:
        proc.kill()
        proc.wait()


def test_process_dying_during_escalation_is_recorded_not_swallowed(monkeypatch):
    """If the process dies from our SIGTERM in the window before the SIGKILL,
    record it as a successful kill (audit intact), not as 'already gone' (which
    falsely implies it was dead before we acted). The race is simulated with a
    narrow stub — a real process can't reproduce the timing deterministically."""
    import psutil

    class _DiesOnEscalation:
        def create_time(self):
            return 0.0

        def send_signal(self, _s):
            pass

        def wait(self, timeout=None):
            raise psutil.TimeoutExpired(timeout or 0)

        def kill(self):
            raise psutil.NoSuchProcess(pid=1)

    monkeypatch.setattr(reap_act, "_self_pid_chain", set)
    monkeypatch.setattr(reap_act.psutil, "Process", lambda _pid: _DiesOnEscalation())
    recorded: list = []
    monkeypatch.setattr(reap_act, "record", lambda event, **kw: recorded.append((event, kw)))

    out = reap_act.terminate([_mk(4200, kind="droid")], dry_run=False, timeout=0.1)

    assert out[0].ok is True
    assert "already gone" not in out[0].message
    assert "SIGTERM" in out[0].message  # "exited after SIGTERM"
    assert any(ev == "reap.kill" for ev, _ in recorded)  # oplog not skipped


def test_pid_reuse_create_time_mismatch_is_skipped():
    """If a target's recorded create_time no longer matches the live process at
    that pid, the pid was recycled — never signal it."""
    import subprocess
    import sys

    import psutil

    proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    try:
        real_ct = psutil.Process(proc.pid).create_time()
        # A wrong create_time means "this pid is now someone else".
        stale = ProcInfo(
            pid=proc.pid,
            ppid=1,
            kind="automation-browser",
            name="Google Chrome",
            cmdline="Google Chrome --headless",
            rss=1,
            cpu_percent=0.0,
            create_time=real_ct - 10_000.0,  # mismatch
            age=0.0,
            tty=None,
            user="me",
            idle_seconds=0.0,
        )
        out = reap_act.terminate([stale], dry_run=False)
        assert out[0].ok is False
        assert "recycl" in out[0].message.lower()
        assert psutil.pid_exists(proc.pid)  # survived — we refused to kill it
    finally:
        proc.kill()
        proc.wait()

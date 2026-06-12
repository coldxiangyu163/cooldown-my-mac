"""Unit tests for the orphan automation-browser detector.

The safety-critical property: the user's *real* browser (default profile,
no automation markers) must never be classified as a reapable leftover.
"""

from __future__ import annotations

import time

from cooldown.collectors import hot_procs as hot_mod
from cooldown.collectors import leftovers as lf

# (name, exe, cmdline) triples.
_REAL = (
    "Google Chrome",
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome "
    "--user-data-dir=/Users/me/Library/Application Support/Google/Chrome",
)
_AUTO = (
    "Google Chrome",
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome "
    "--remote-debugging-port=0 --user-data-dir=/var/folders/x/T/agent-browser-chrome-abc",
)


def test_classify_skips_real_default_profile_browser():
    """The guard: a default-profile browser is never a leftover."""
    assert lf.classify_browser_origin(*_REAL) is None


def test_classify_flags_temp_profile_automation_browser():
    o = lf.classify_browser_origin(*_AUTO)
    assert o is not None
    assert o.tool == "agent-browser"
    assert o.reason == "temp-profile"


def test_classify_flags_headless_without_temp_profile():
    o = lf.classify_browser_origin("Chromium", "/x/Chromium", "Chromium --headless --enable-automation")
    assert o is not None
    assert o.reason == "automation-flag"


def test_classify_flags_by_automation_parent():
    o = lf.classify_browser_origin(
        "Google Chrome",
        "/x/Google Chrome",
        "Google Chrome",
        parent_name="agent-browser-darwin-arm64",
    )
    assert o is not None
    assert o.reason == "automation-parent"


def test_classify_ignores_non_browser():
    assert lf.classify_browser_origin("python3.13", "/usr/bin/python3.13", "python3.13 x.py") is None


def test_browser_aware_key_splits_automation_from_real():
    name, exe, cmd = _REAL
    assert lf.browser_aware_key(exe, cmd, name) == "Google Chrome"
    name, exe, cmd = _AUTO
    assert lf.browser_aware_key(exe, cmd, name) == "Google Chrome (agent-browser)"


def test_annotate_origins_flags_only_the_automation_group():
    """End-to-end: real and automation Chrome land in separate groups, and
    only the automation one gets an origin — the real browser stays clean."""

    def _proc(pid, triple):
        name, exe, cmd = triple
        return hot_mod.HotProc(
            pid=pid,
            name=name,
            cmdline=cmd,
            cpu_percent=5.0,
            rss=1,
            user="u",
            create_time=0.0,
            age=1.0,
            exe=exe,
        )

    apps, _ = hot_mod.aggregate_by_app(
        [_proc(1, _REAL), _proc(2, _AUTO)],
        ncpu=10,
        top_n=8,
        key_fn=lf.browser_aware_key,
    )
    lf.annotate_origins(apps)
    by_name = {a.app: a for a in apps}
    assert by_name["Google Chrome"].origin is None
    assert by_name["Google Chrome (agent-browser)"].origin is not None


class _FakeProc:
    """Minimal psutil.Process stand-in for ``collect`` tests."""

    def __init__(
        self, pid, name, *, ppid=1, cmdline="", create_time=0.0, children=(), cpu=0.0
    ):
        self.pid = pid
        self.info = {"pid": pid, "name": name, "ppid": ppid}
        self._cmdline = cmdline
        self._ct = create_time
        self._children = list(children)
        self._cpu = cpu

    def cmdline(self):
        return self._cmdline.split() if self._cmdline else []

    def create_time(self):
        return self._ct

    def cpu_percent(self, _interval=None):
        return self._cpu

    def name(self):
        return self.info["name"]

    def exe(self):
        return ""

    def username(self):
        return "u"

    def children(self, recursive=False):
        return self._children

    def memory_info(self):
        class _M:
            rss = 1000

        return _M()


def test_collect_picks_automation_browser_not_real(monkeypatch):
    now = time.time()
    real = _FakeProc(1, "Google Chrome", cmdline=_REAL[2], create_time=now)
    auto = _FakeProc(2, "Google Chrome", cmdline=_AUTO[2], create_time=now)
    monkeypatch.setattr(lf.psutil, "process_iter", lambda attrs=None: iter([real, auto]))

    out = lf.collect(sample_interval=0.0)

    assert {p.pid for p in out} == {2}  # only the automation browser
    assert out[0].kind == "automation-browser"


def test_collect_finds_leaked_launcher(monkeypatch):
    """An agent-browser launcher with no live browser child, older than the
    leak threshold, is a reapable leftover."""
    old = time.time() - 7200
    launcher = _FakeProc(3, "agent-browser-darwin-arm64", cmdline="/x/agent-browser", create_time=old)
    monkeypatch.setattr(lf.psutil, "process_iter", lambda attrs=None: iter([launcher]))

    out = lf.collect(leak_age_seconds=1800, sample_interval=0.0)

    assert [p.pid for p in out] == [3]


def test_collect_keeps_fresh_launcher(monkeypatch):
    """A launcher younger than the threshold is not yet a leftover."""
    fresh = _FakeProc(4, "agent-browser-darwin-arm64", cmdline="/x/agent-browser", create_time=time.time())
    monkeypatch.setattr(lf.psutil, "process_iter", lambda attrs=None: iter([fresh]))

    assert lf.collect(leak_age_seconds=1800, sample_interval=0.0) == []


def test_collect_samples_real_cpu_percent(monkeypatch):
    """A leaked browser's CPU% is sampled (normalized per core), not hardcoded
    to 0.0 — this is the signal that answers 'which leftover is cooking the
    CPU'."""
    now = time.time()
    auto = _FakeProc(2, "Google Chrome", cmdline=_AUTO[2], create_time=now, cpu=80.0)
    monkeypatch.setattr(lf.psutil, "process_iter", lambda attrs=None: iter([auto]))
    monkeypatch.setattr(lf.psutil, "cpu_count", lambda logical=True: 8)

    out = lf.collect(sample_interval=0.0)

    assert out[0].cpu_percent == 10.0  # 80 raw / 8 cores


def test_collect_carries_real_create_time(monkeypatch):
    """create_time must be carried (not zeroed) so the killer can validate
    PID identity before reaping a subtree."""
    ct = 1_700_000_000.0
    auto = _FakeProc(2, "Google Chrome", cmdline=_AUTO[2], create_time=ct)
    monkeypatch.setattr(lf.psutil, "process_iter", lambda attrs=None: iter([auto]))

    out = lf.collect(sample_interval=0.0)

    assert out[0].create_time == ct


def test_collect_dedups_helper_under_browser_root(monkeypatch):
    """Chrome's renderer/gpu helpers (``--type=``) are torn down with their
    parent browser, so only the root browser process is surfaced; the killer
    reaps the subtree."""
    now = time.time()
    root = _FakeProc(10, "Google Chrome", ppid=1, cmdline=_AUTO[2], create_time=now)
    helper = _FakeProc(
        11,
        "Google Chrome Helper (Renderer)",
        ppid=10,
        cmdline=(
            "Google Chrome Helper --type=renderer "
            "--user-data-dir=/var/folders/x/T/agent-browser-chrome-abc"
        ),
        create_time=now,
    )
    monkeypatch.setattr(lf.psutil, "process_iter", lambda attrs=None: iter([root, helper]))

    out = lf.collect(sample_interval=0.0)

    assert {p.pid for p in out} == {10}  # only the root, helper deduped


def test_collect_emits_orphaned_helper(monkeypatch):
    """A helper whose parent browser is gone (reparented to launchd, ppid 1)
    is no longer covered by a root's subtree, so it must be surfaced on its
    own."""
    now = time.time()
    orphan_helper = _FakeProc(
        12,
        "Google Chrome Helper (Renderer)",
        ppid=1,  # parent browser gone
        cmdline=(
            "Google Chrome Helper --type=renderer "
            "--user-data-dir=/var/folders/x/T/agent-browser-chrome-abc"
        ),
        create_time=now,
    )
    monkeypatch.setattr(lf.psutil, "process_iter", lambda attrs=None: iter([orphan_helper]))

    out = lf.collect(sample_interval=0.0)

    assert {p.pid for p in out} == {12}


def test_is_helper_detects_type_flag():
    assert lf.is_helper("Google Chrome --type=renderer") is True
    assert lf.is_helper("Google Chrome --remote-debugging-port=0") is False


def test_collect_surfaces_origin_and_orphan_in_cmdline(monkeypatch):
    """The origin + orphan classification must reach the user: it is prefixed
    onto the displayed cmdline (the reap table's only text column), not thrown
    away. ppid<=1 (reparented to launchd) flags an orphan."""
    auto = _FakeProc(2, "Google Chrome", ppid=1, cmdline=_AUTO[2], create_time=time.time())
    monkeypatch.setattr(lf.psutil, "process_iter", lambda attrs=None: iter([auto]))

    out = lf.collect(sample_interval=0.0)

    assert "agent-browser" in out[0].cmdline
    assert "orphan" in out[0].cmdline


def test_collect_idle_seconds_tracks_age(monkeypatch):
    """The daemon's freshness gate depends on idle_seconds faithfully tracking
    process age, so a freshly-spawned automation browser is NOT mistaken for a
    stale leftover."""
    fresh = _FakeProc(2, "Google Chrome", cmdline=_AUTO[2], create_time=time.time())
    old = _FakeProc(3, "Google Chrome", cmdline=_AUTO[2], create_time=time.time() - 7200)
    monkeypatch.setattr(lf.psutil, "process_iter", lambda attrs=None: iter([fresh, old]))

    out = {p.pid: p for p in lf.collect(sample_interval=0.0)}

    assert out[2].idle_seconds is not None and out[2].idle_seconds < 60
    assert out[3].idle_seconds is not None and out[3].idle_seconds >= 7000


def test_classify_skips_real_browser_without_user_data_dir():
    """A real browser launched from the Dock often has NO --user-data-dir at
    all; it must still never classify as a leftover."""
    assert (
        lf.classify_browser_origin(
            "Google Chrome",
            "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
            "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        )
        is None
    )


def test_is_temp_profile_flags_genuine_automation_dir():
    """A throwaway profile whose dir *begins* with a tool name is automation."""
    assert lf.is_temp_profile("/var/folders/x/T/agent-browser-chrome-abc") is True
    assert lf.is_temp_profile("/Users/me/Library/Caches/ms-playwright/chromium/Default") is True


def test_is_temp_profile_ignores_marker_buried_in_unrelated_segment():
    """Safety hardening: a real profile under a dir that merely *contains* a
    tool name as a substring (not a segment start) must NOT be read as a
    throwaway profile, or the user's real browser could be reaped."""
    real = "/Users/me/Library/Application Support/my-agent-browser-notes/Chrome"
    assert lf.is_temp_profile(real) is False
    # And classification of a real browser pointed there stays None.
    cmd = f"/Applications/Google Chrome.app/Contents/MacOS/Google Chrome --user-data-dir={real}"
    assert lf.classify_browser_origin("Google Chrome", "/Applications/Google Chrome.app/x", cmd) is None


def test_collect_spares_launcher_with_live_browser_child(monkeypatch):
    """Safety check: an old launcher that still has a live browser child is an
    ACTIVE session, not a leak — it must never be reaped."""
    old = time.time() - 7200
    chrome = _FakeProc(21, "Google Chrome", ppid=20, create_time=old)
    launcher = _FakeProc(
        20, "agent-browser-darwin-arm64", cmdline="/x/agent-browser",
        create_time=old, children=(chrome,),
    )
    monkeypatch.setattr(lf.psutil, "process_iter", lambda attrs=None: iter([launcher]))

    assert lf.collect(leak_age_seconds=1800, sample_interval=0.0) == []


def test_collect_spares_geckodriver_with_live_firefox_child(monkeypatch):
    """geckodriver drives Firefox, not Chromium. An old geckodriver with a live
    Firefox child is an active Selenium session and must be spared — the
    'has live browser child' check has to recognize Firefox too."""
    old = time.time() - 7200
    firefox = _FakeProc(31, "firefox", ppid=30, create_time=old)
    gecko = _FakeProc(
        30, "geckodriver", cmdline="/x/geckodriver", create_time=old, children=(firefox,)
    )
    monkeypatch.setattr(lf.psutil, "process_iter", lambda attrs=None: iter([gecko]))

    assert lf.collect(leak_age_seconds=1800, sample_interval=0.0) == []


def test_collect_finds_leaked_geckodriver(monkeypatch):
    """A geckodriver with no live browser child, older than the threshold, is a
    reapable leftover (parity with the agent-browser launcher case)."""
    old = time.time() - 7200
    gecko = _FakeProc(32, "geckodriver", cmdline="/x/geckodriver", create_time=old)
    monkeypatch.setattr(lf.psutil, "process_iter", lambda attrs=None: iter([gecko]))

    assert [p.pid for p in lf.collect(leak_age_seconds=1800, sample_interval=0.0)] == [32]

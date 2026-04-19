from cooldown.actions import launchd as launchd_act
from cooldown.collectors import launchd as launchd_mod

FAKE_LIST = """\
PID\tStatus\tLabel
-\t0\tcom.apple.mdworker
1234\t0\tcom.tencent.WeChatAppEx.launcher
-\t0\tcom.example.customtool
5678\t-1\tcom.example.crasher
99\t0\thomebrew.mxcl.postgresql@14
"""


def test_parse_launchctl_list():
    rows = launchd_mod._parse_list(FAKE_LIST)
    labels = [r[2] for r in rows]
    assert "com.apple.mdworker" in labels
    assert "com.example.crasher" in labels
    # status column preserved
    crasher = next(r for r in rows if r[2] == "com.example.crasher")
    assert crasher[0] == 5678
    assert crasher[1] == -1


def test_categorization_without_plist_paths():
    # Collect is driven by our fake list; plist index is whatever happens to
    # exist on the test machine so we tolerate multiple outcomes.
    entries = launchd_mod.collect(list_output=FAKE_LIST)
    by_label = {e.label: e for e in entries}

    # com.apple.* without a plist path still lands in "apple" via
    # label-only fallback.
    assert by_label["com.apple.mdworker"].category == "apple"

    # com.tencent.WeChat* is unknown when we can't resolve a plist; the
    # important contract is that `suspicious()` flags it regardless.
    wechat = by_label["com.tencent.WeChatAppEx.launcher"]
    assert wechat.pid == 1234
    suspicious_labels = {e.label for e in launchd_mod.suspicious(entries)}
    assert "com.tencent.WeChatAppEx.launcher" in suspicious_labels
    # Crasher (non-zero last_exit_status) also flagged.
    assert "com.example.crasher" in suspicious_labels


def test_disable_refuses_apple_category():
    entry = launchd_mod.LaunchdEntry(
        label="com.apple.something",
        domain="system",
        pid=None,
        last_exit_status=0,
        path="/System/Library/LaunchDaemons/com.apple.something.plist",
        category="apple",
        enabled=True,
    )
    outcome = launchd_act.disable(entry, dry_run=True)
    assert outcome.ok is False
    assert "refuses" in outcome.message


def test_disable_dry_run_for_third_party():
    entry = launchd_mod.LaunchdEntry(
        label="com.example.tool",
        domain="gui",
        pid=None,
        last_exit_status=0,
        path=None,
        category="third-party",
        enabled=True,
    )
    outcome = launchd_act.disable(entry, dry_run=True)
    assert outcome.ok is True
    assert outcome.message.startswith("dry-run:")
    assert "bootout" in outcome.message


def test_enable_requires_plist_path():
    entry = launchd_mod.LaunchdEntry(
        label="com.example.tool",
        domain="gui",
        pid=None,
        last_exit_status=0,
        path=None,
        category="third-party",
        enabled=True,
    )
    outcome = launchd_act.enable(entry, dry_run=True)
    assert outcome.ok is False
    assert "plist" in outcome.message

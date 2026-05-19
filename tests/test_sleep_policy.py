from cooldown.actions import sleep_policy

PMSET_OUT = """\
System-wide power settings:
Currently in use:
 standby              0
 Sleep On Power Button 1
 hibernatefile        /var/vm/sleepimage
 powernap             1
 networkoversleep     0
 disksleep            10
 sleep                5 (sleep prevented by deviced)
 displaysleep         2
 ttyskeepawake        1
 lowpowermode         0
"""


def test_current_parses_pmset(mocker):
    mocker.patch.object(sleep_policy, "_pmset_g", return_value=PMSET_OUT)
    p = sleep_policy.current()
    assert p.displaysleep == 2
    assert p.disksleep == 10
    assert p.powernap is True


def test_apply_is_idempotent(mocker):
    mocker.patch.object(sleep_policy, "_pmset_g", return_value=PMSET_OUT)
    sudo = mocker.patch.object(sleep_policy, "_sudo_pmset")

    same = sleep_policy.SleepPolicy(displaysleep=2, disksleep=10, powernap=True)
    out = sleep_policy.apply(same, source="ac")
    assert out.ok is True
    assert out.changed is False
    sudo.assert_not_called()


def test_apply_changes_when_only_powernap_differs(mocker):
    mocker.patch.object(sleep_policy, "_pmset_g", return_value=PMSET_OUT)
    called = {}

    def fake_sudo(args, *, dry_run):
        called["args"] = args
        return sleep_policy.ApplyOutcome(True, True, "applied")

    mocker.patch.object(sleep_policy, "_sudo_pmset", side_effect=fake_sudo)

    target = sleep_policy.SleepPolicy(displaysleep=2, disksleep=10, powernap=False)
    out = sleep_policy.apply(target, source="ac", dry_run=True)
    assert out.ok is True
    assert out.changed is True
    assert called["args"][-2:] == ["powernap", "0"]


def test_apply_calls_sudo_pmset_on_change(mocker):
    mocker.patch.object(sleep_policy, "_pmset_g", return_value=PMSET_OUT)
    called = {}

    def fake_sudo(args, *, dry_run):
        called["args"] = args
        called["dry_run"] = dry_run
        return sleep_policy.ApplyOutcome(True, True, "applied")

    mocker.patch.object(sleep_policy, "_sudo_pmset", side_effect=fake_sudo)

    target = sleep_policy.SleepPolicy(displaysleep=10, disksleep=10, powernap=False)
    out = sleep_policy.apply(target, source="ac", dry_run=True)
    assert out.ok is True
    assert out.changed is True
    assert called["dry_run"] is True
    assert called["args"][0] == "-c"
    assert "displaysleep" in called["args"]
    assert "10" in called["args"]
    assert called["args"][-2:] == ["powernap", "0"]


def test_restore_defaults_dry_run(mocker):
    mocker.patch.object(sleep_policy, "_pmset_g", return_value=PMSET_OUT)
    mocker.patch.object(
        sleep_policy,
        "_sudo_pmset",
        return_value=sleep_policy.ApplyOutcome(True, True, "applied"),
    )
    out = sleep_policy.restore_defaults(dry_run=True)
    assert out.ok is True


def test_source_flag_mapping(mocker):
    mocker.patch.object(sleep_policy, "_pmset_g", return_value=PMSET_OUT)
    seen = {}

    def fake_sudo(args, *, dry_run):
        seen["args"] = args
        return sleep_policy.ApplyOutcome(True, True, "applied")

    mocker.patch.object(sleep_policy, "_sudo_pmset", side_effect=fake_sudo)
    target = sleep_policy.SleepPolicy(displaysleep=20, disksleep=20, powernap=False)
    sleep_policy.apply(target, source="battery")
    assert seen["args"][0] == "-b"
    sleep_policy.apply(target, source="all")
    assert seen["args"][0] == "-a"

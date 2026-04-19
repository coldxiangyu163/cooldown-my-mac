from cooldown.util import bar, human_bytes, human_duration


def test_human_bytes():
    assert human_bytes(0) == "0B"
    assert human_bytes(1023) == "1023B"
    assert human_bytes(1024) == "1.0KB"
    assert human_bytes(10 * 1024**3) == "10.0GB"


def test_human_duration():
    assert human_duration(5) == "5s"
    assert human_duration(65) == "1m05s"
    assert human_duration(3661) == "1h01m"
    assert human_duration(90061).startswith("1d")


def test_bar():
    assert len(bar(0)) == 20
    assert len(bar(100)) == 20
    assert bar(0).count("░") == 20
    assert bar(100).count("█") == 20
    assert bar(50).count("█") == 10

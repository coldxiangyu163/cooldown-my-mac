"""Tests for `cool ports` — collector parsing + UI happy path."""
from __future__ import annotations

import subprocess

from rich.console import Console

from cooldown.collectors import ports as ports_mod
from cooldown.collectors.ports import PortEntry
from cooldown.ui import ports as ports_ui

# Canned `lsof -iTCP -sTCP:LISTEN -P -n -F pcnPLT` output. Three processes:
#   - node pid=100 listens on *:3000 (tcp4) and [::]:3000 (tcp6)
#     ⇒ same pid, not a conflict even though port matches.
#   - ruby pid=200 listens on 127.0.0.1:3000 (tcp4)
#     ⇒ DIFFERENT pid on the same port ⇒ conflict with node.
#   - postgres pid=300 listens on [::1]:5432 (tcp6 only).
_LSOF_FIXTURE = """\
p100
cnode
Lme
f6
PTCP
n*:3000
TST=LISTEN
f8
PTCP
n[::]:3000
TST=LISTEN
p200
cruby
Lme
f4
PTCP
n127.0.0.1:3000
TST=LISTEN
p300
cpostgres
L_postgres
f12
PTCP
n[::1]:5432
TST=LISTEN
"""


def _fake_run(*args, **kwargs):  # noqa: ANN001, ARG001
    return subprocess.CompletedProcess(
        args=args[0] if args else [],
        returncode=0,
        stdout=_LSOF_FIXTURE,
        stderr="",
    )


def test_collect_parses_fixture(mocker):
    mocker.patch("cooldown.collectors.ports.subprocess.run", side_effect=_fake_run)
    entries = ports_mod.collect()
    # 4 sockets total across 3 pids.
    assert len(entries) == 4

    # Index by (pid, port, bind) for order-tolerant assertions.
    idx = {(e.pid, e.port, e.bind): e for e in entries}

    node_v4 = idx[(100, 3000, "*")]
    assert node_v4.proto == "tcp4"
    assert node_v4.process == "node"
    assert node_v4.user == "me"

    node_v6 = idx[(100, 3000, "::")]
    assert node_v6.proto == "tcp6"

    ruby = idx[(200, 3000, "127.0.0.1")]
    assert ruby.proto == "tcp4"
    assert ruby.process == "ruby"

    pg = idx[(300, 5432, "::1")]
    assert pg.proto == "tcp6"
    assert pg.process == "postgres"
    assert pg.user == "_postgres"


def test_collect_returns_empty_when_lsof_errors(mocker):
    def _boom(*_a, **_kw):
        raise FileNotFoundError("lsof: not found")

    mocker.patch("cooldown.collectors.ports.subprocess.run", side_effect=_boom)
    assert ports_mod.collect() == []


def test_range_filter_inclusive_bounds():
    entries = [
        PortEntry(port=80, proto="tcp4", bind="*", pid=1, process="a", user="u"),
        PortEntry(port=443, proto="tcp4", bind="*", pid=1, process="a", user="u"),
        PortEntry(port=3000, proto="tcp4", bind="*", pid=2, process="b", user="u"),
        PortEntry(port=8080, proto="tcp4", bind="*", pid=3, process="c", user="u"),
    ]
    got = ports_mod.range_filter(entries, 443, 3000)
    assert {e.port for e in got} == {443, 3000}

    # Boundaries hit exactly.
    got_single = ports_mod.range_filter(entries, 80, 80)
    assert [e.port for e in got_single] == [80]

    # Start/end swapped still works.
    got_rev = ports_mod.range_filter(entries, 3000, 443)
    assert {e.port for e in got_rev} == {443, 3000}


def test_find_conflicts_same_pid_ipv4_ipv6_not_a_conflict():
    entries = [
        PortEntry(port=3000, proto="tcp4", bind="*", pid=100, process="node", user="me"),
        PortEntry(port=3000, proto="tcp6", bind="::", pid=100, process="node", user="me"),
    ]
    assert ports_mod.find_conflicts(entries) == []


def test_find_conflicts_different_pids_same_port_is_conflict():
    entries = [
        PortEntry(port=3000, proto="tcp4", bind="*", pid=100, process="node", user="me"),
        PortEntry(port=3000, proto="tcp6", bind="::", pid=100, process="node", user="me"),
        PortEntry(port=3000, proto="tcp4", bind="127.0.0.1", pid=200, process="ruby", user="me"),
        PortEntry(port=5432, proto="tcp6", bind="::1", pid=300, process="pg", user="pg"),
    ]
    conflicts = ports_mod.find_conflicts(entries)
    assert len(conflicts) == 1
    port, group = conflicts[0]
    assert port == 3000
    assert {e.pid for e in group} == {100, 200}


def test_by_project_hint_known_ports():
    assert ports_mod.by_project_hint(3306) == "mysql"
    assert ports_mod.by_project_hint(5432) == "postgres"
    assert ports_mod.by_project_hint(6379) == "redis"
    assert ports_mod.by_project_hint(27017) == "mongo"
    assert ports_mod.by_project_hint(9200) == "elastic"
    assert ports_mod.by_project_hint(9222) == "chrome-devtools"
    assert ports_mod.by_project_hint(5900) == "vnc"
    assert ports_mod.by_project_hint(22) == "ssh"
    assert ports_mod.by_project_hint(80) == "http"
    assert ports_mod.by_project_hint(443) == "https"
    assert ports_mod.by_project_hint(12345) is None


def test_ui_run_empty_returns_zero(monkeypatch):
    # Stub ancestry / project to ensure we never accidentally touch them
    # even if the parallel worker's modules get imported later.
    monkeypatch.setattr(ports_ui, "_ancestry_mod", None, raising=False)
    monkeypatch.setattr(ports_ui, "_project_mod", None, raising=False)

    # Stub the collector to return nothing — ui.run must still exit cleanly.
    monkeypatch.setattr(ports_mod, "collect", lambda: [])
    console = Console(force_terminal=False)
    rc = ports_ui.run(console)
    assert rc == 0


def test_ui_run_free_range_with_no_entries(monkeypatch):
    monkeypatch.setattr(ports_ui, "_ancestry_mod", None, raising=False)
    monkeypatch.setattr(ports_ui, "_project_mod", None, raising=False)
    monkeypatch.setattr(ports_mod, "collect", lambda: [])
    console = Console(force_terminal=False)
    assert ports_ui.run(console, free="4000:4005") == 0

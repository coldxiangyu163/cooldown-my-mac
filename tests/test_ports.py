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


def test_collapse_inherited_folds_reloader_child():
    """Parent + forked child sharing one listening socket should collapse
    to one row with the child surfaced as a worker — the uvicorn
    ``--reload`` / flask debug-server case from the dashboard."""
    parent = PortEntry(port=8000, proto="tcp4", bind="*", pid=19873,
                       process="python3.13", user="me")
    child = PortEntry(port=8000, proto="tcp4", bind="*", pid=31043,
                      process="python3.13", user="me")
    ancestors = {19873: set(), 31043: {19873}}

    kept, workers = ports_mod.collapse_inherited([parent, child], ancestors)
    assert [e.pid for e in kept] == [19873]
    assert workers == {19873: [31043]}


def test_collapse_inherited_keeps_unrelated_same_port():
    """Two unrelated PIDs on the same port (the real conflict case)
    must stay split — we don't have evidence one inherited from the
    other, so collapsing would hide a genuine conflict."""
    a = PortEntry(port=3000, proto="tcp4", bind="*", pid=100,
                  process="node", user="me")
    b = PortEntry(port=3000, proto="tcp4", bind="127.0.0.1", pid=200,
                  process="ruby", user="me")
    # Neither pid appears in the other's ancestor chain.
    ancestors = {100: {1}, 200: {1}}

    kept, workers = ports_mod.collapse_inherited([a, b], ancestors)
    assert sorted(e.pid for e in kept) == [100, 200]
    assert workers == {}


def test_collapse_inherited_handles_grandchild_chain():
    """Three-deep chain (parent → reloader → worker) folds onto the
    top-most ancestor in the group, not the middle one."""
    a = PortEntry(port=8000, proto="tcp4", bind="*", pid=1,
                  process="python3.13", user="me")
    b = PortEntry(port=8000, proto="tcp4", bind="*", pid=2,
                  process="python3.13", user="me")
    c = PortEntry(port=8000, proto="tcp4", bind="*", pid=3,
                  process="python3.13", user="me")
    ancestors = {1: set(), 2: {1}, 3: {2, 1}}

    kept, workers = ports_mod.collapse_inherited([a, b, c], ancestors)
    assert [e.pid for e in kept] == [1]
    assert sorted(workers[1]) == [2, 3]


def test_collapse_inherited_no_ancestors_keeps_all():
    """When ancestry data is missing (CLI without optional ancestry
    collector), the helper must degrade to a no-op so existing rows
    aren't silently dropped."""
    a = PortEntry(port=3000, proto="tcp4", bind="*", pid=100,
                  process="node", user="me")
    b = PortEntry(port=3000, proto="tcp4", bind="*", pid=200,
                  process="ruby", user="me")
    kept, workers = ports_mod.collapse_inherited([a, b], {})
    assert sorted(e.pid for e in kept) == [100, 200]
    assert workers == {}


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


def test_ui_run_json_includes_workers_after_collapse(monkeypatch):
    """`cool ports --json` must expose the inherited-worker PIDs so
    scripted callers see the same row count `cool watch` does."""
    parent = PortEntry(port=8000, proto="tcp4", bind="*", pid=19873,
                       process="python3.13", user="me")
    child = PortEntry(port=8000, proto="tcp4", bind="*", pid=31043,
                      process="python3.13", user="me")

    monkeypatch.setattr(ports_mod, "collect", lambda: [parent, child])
    monkeypatch.setattr(ports_mod, "enrich_command", lambda _entries: None)
    monkeypatch.setattr(ports_ui, "_project_mod", None, raising=False)
    # Synthetic ancestry: child inherits from parent.
    monkeypatch.setattr(
        ports_ui, "_ancestors_for", lambda _pids: {19873: set(), 31043: {19873}}
    )

    console = Console(record=True, width=200, force_terminal=False)
    rc = ports_ui.run(console, json_out=True)
    assert rc == 0

    import json as _json

    payload = _json.loads(console.export_text())
    assert len(payload) == 1
    row = payload[0]
    assert row["pid"] == 19873
    assert row["workers"] == [31043]

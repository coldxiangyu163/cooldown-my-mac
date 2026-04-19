"""Unit tests for `cooldown.collectors.project`."""
from __future__ import annotations

import os
from pathlib import Path

from cooldown.collectors import project as project_mod


def test_find_root_simple(tmp_path: Path):
    (tmp_path / "package.json").write_text("{}")
    nested = tmp_path / "src" / "lib"
    nested.mkdir(parents=True)

    got = project_mod.find_root(nested)
    assert got is not None
    assert got.root == tmp_path.resolve()
    assert got.name == tmp_path.name
    assert "package.json" in got.markers


def test_find_root_returns_none_when_no_marker(tmp_path: Path):
    nested = tmp_path / "a" / "b"
    nested.mkdir(parents=True)
    assert project_mod.find_root(nested) is None


def test_find_root_marker_priority(tmp_path: Path):
    # The highest-priority marker comes first in the list even if we drop
    # several in the same directory. `.git` is at position 0 in MARKERS.
    (tmp_path / ".git").mkdir()
    (tmp_path / "package.json").write_text("{}")
    got = project_mod.find_root(tmp_path)
    assert got is not None
    assert got.markers[0] == ".git"
    assert "package.json" in got.markers


def test_find_root_stops_at_first_match(tmp_path: Path):
    # Parent has marker; child has marker too → we return the child.
    outer = tmp_path
    (outer / "pyproject.toml").write_text("")
    inner = outer / "sub"
    inner.mkdir()
    (inner / "Cargo.toml").write_text("")

    got = project_mod.find_root(inner)
    assert got is not None
    assert got.root == inner.resolve()
    assert "Cargo.toml" in got.markers


def test_find_root_respects_max_depth(tmp_path: Path):
    (tmp_path / "package.json").write_text("{}")
    # Build a 12-deep path; max_depth default 10 means we can reach it,
    # but max_depth=2 must miss.
    deep = tmp_path
    for i in range(12):
        deep = deep / f"d{i}"
    deep.mkdir(parents=True)
    assert project_mod.find_root(deep, max_depth=2) is None
    assert project_mod.find_root(deep, max_depth=15) is not None


def test_get_cwd_current_process():
    got = project_mod.get_cwd(os.getpid())
    assert got is not None
    assert Path(got).is_dir()


def test_get_cwd_nonexistent_pid():
    # A pid that almost certainly doesn't exist.
    got = project_mod.get_cwd(999_999_999)
    assert got is None


def test_lookup_integrates(tmp_path: Path, mocker):
    (tmp_path / "pyproject.toml").write_text("")
    mocker.patch.object(project_mod, "get_cwd", return_value=str(tmp_path))
    got = project_mod.lookup(12345)
    assert got is not None
    assert got.root == tmp_path.resolve()


def test_markers_tuple_shape():
    # Simple shape/regression guard — markers is a tuple of str and
    # `.git` must be first (priority).
    assert isinstance(project_mod.MARKERS, tuple)
    assert project_mod.MARKERS[0] == ".git"

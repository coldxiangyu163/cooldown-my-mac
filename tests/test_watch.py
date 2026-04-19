"""Smoke tests for the Textual-backed `cool watch` dashboard.

Skips entirely when the optional ``textual`` dependency is not installed.
"""
from __future__ import annotations

import pytest

pytest.importorskip("textual")

from cooldown.ui import watch  # noqa: E402


def _binding_keys(bindings) -> set[str]:
    """Return the set of keys declared in a Textual ``BINDINGS`` list.

    ``BINDINGS`` may contain either tuples ``(key, action, description)`` or
    ``textual.binding.Binding`` instances. Compound keys like ``"plus,equals"``
    are split so each individual key is checked.
    """
    keys: set[str] = set()
    for b in bindings:
        raw = b[0] if isinstance(b, tuple) else getattr(b, "key", "")
        for chunk in str(raw).split(","):
            chunk = chunk.strip()
            if chunk:
                keys.add(chunk)
    return keys


def test_watch_module_does_not_import_textual_eagerly():
    # Simply importing the module must succeed without textual being loaded
    # as a side-effect of cooldown.ui.watch itself — the module does a lazy
    # import inside ``_build_app_class`` / ``run``.
    import importlib

    mod = importlib.import_module("cooldown.ui.watch")
    # textual is present in this test env (importorskip above), but the
    # watch module must not re-export it or bind it at module scope.
    assert not hasattr(mod, "App")
    assert not hasattr(mod, "Static")


def test_watch_app_has_required_bindings():
    app_cls = watch._build_app_class()
    keys = _binding_keys(app_cls.BINDINGS)
    for expected in ("q", "r", "p"):
        assert expected in keys, f"missing binding: {expected!r} (have {keys})"


def test_watch_app_compose_yields_at_least_four_widgets():
    app_cls = watch._build_app_class()
    app = app_cls(interval=3)
    widgets = list(app.compose())
    assert len(widgets) >= 4, f"expected >= 4 top-level widgets, got {len(widgets)}"


def test_watch_app_title_and_default_interval():
    app_cls = watch._build_app_class()
    app = app_cls()
    assert app.interval == 3
    assert app.TITLE == "cooldown · watch"
    assert app.paused is False


def test_run_without_textual_prints_hint(monkeypatch):
    """When textual cannot be imported, ``run`` must return non-zero and
    print a clear install hint rather than raising."""
    from rich.console import Console

    def _raise(*_a, **_kw):
        raise ImportError("textual missing (simulated)")

    monkeypatch.setattr(watch, "_build_app_class", _raise)

    buf_console = Console(record=True, width=100)
    rc = watch.run(buf_console, interval=3)
    assert rc != 0
    output = buf_console.export_text()
    assert "textual is not installed" in output
    assert "pip install textual" in output or "pipx inject" in output

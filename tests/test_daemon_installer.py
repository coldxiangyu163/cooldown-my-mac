"""Installer tests: plist rendering + mocked launchctl bootstrap/bootout."""
from __future__ import annotations

import plistlib
import subprocess
from pathlib import Path

import pytest

from cooldown.daemon import installer as installer_mod


@pytest.fixture
def temp_home(tmp_path: Path, monkeypatch):
    """Redirect plist_path/_log_dir into a temp home so we don't touch ~."""
    fake_plist = tmp_path / "LaunchAgents" / "ai.cooldown.agent.plist"
    fake_logs = tmp_path / "Logs"
    monkeypatch.setattr(installer_mod, "plist_path", lambda: fake_plist)
    monkeypatch.setattr(installer_mod, "_log_dir", lambda: fake_logs)
    monkeypatch.setattr(installer_mod, "_working_directory", lambda: tmp_path / "home")
    (tmp_path / "home").mkdir(parents=True, exist_ok=True)
    return tmp_path


def _fake_cp(returncode: int = 0, stdout: str = "", stderr: str = ""):
    return subprocess.CompletedProcess(
        args=["launchctl"], returncode=returncode, stdout=stdout, stderr=stderr
    )


def test_render_plist_is_valid_xml_and_contains_executable(temp_home, monkeypatch):
    monkeypatch.setattr(installer_mod, "_launchctl", lambda *a, **k: _fake_cp(0))
    outcome = installer_mod.install(executable="/opt/cool/cool")
    assert outcome.ok is True
    plist_file = installer_mod.plist_path()
    assert plist_file.exists()
    data = plistlib.loads(plist_file.read_bytes())
    assert data["Label"] == "ai.cooldown.agent"
    assert data["ProgramArguments"][0] == "/opt/cool/cool"
    assert "daemon" in data["ProgramArguments"]
    assert "run" in data["ProgramArguments"]
    assert data["RunAtLoad"] is True
    assert data["ProcessType"] == "Background"
    assert data["Nice"] == 5
    assert isinstance(data["StandardOutPath"], str)
    assert isinstance(data["StandardErrorPath"], str)
    # Must not contain unresolved template placeholders.
    raw = plist_file.read_text(encoding="utf-8")
    assert "{{" not in raw
    assert "}}" not in raw


def test_install_dry_run_does_not_write(temp_home, monkeypatch):
    called: list[str] = []

    def _fake_launchctl(args, check=False):
        called.append(" ".join(args))
        return _fake_cp(0)

    monkeypatch.setattr(installer_mod, "_launchctl", _fake_launchctl)
    outcome = installer_mod.install(dry_run=True)
    assert outcome.ok is True
    assert not installer_mod.plist_path().exists()
    # dry run should not invoke launchctl at all
    assert called == []


def test_install_bootstrap_failure_reports_error(temp_home, monkeypatch):
    calls: list[list[str]] = []

    def _fake_launchctl(args, check=False):
        calls.append(args)
        if args[0] == "bootstrap":
            return _fake_cp(returncode=1, stderr="boom")
        return _fake_cp(0)

    monkeypatch.setattr(installer_mod, "_launchctl", _fake_launchctl)
    outcome = installer_mod.install(executable="/usr/local/bin/cool")
    assert outcome.ok is False
    assert any("bootstrap failed" in m for m in outcome.messages)


def test_uninstall_removes_plist(temp_home, monkeypatch):
    monkeypatch.setattr(installer_mod, "_launchctl", lambda *a, **k: _fake_cp(0))
    # Create a plist to remove.
    installer_mod.install(executable="/usr/local/bin/cool")
    assert installer_mod.plist_path().exists()

    outcome = installer_mod.uninstall()
    assert outcome.ok is True
    assert not installer_mod.plist_path().exists()


def test_uninstall_when_not_installed(temp_home, monkeypatch):
    monkeypatch.setattr(installer_mod, "_launchctl", lambda *a, **k: _fake_cp(1, stderr="no"))
    outcome = installer_mod.uninstall()
    assert outcome.ok is True


def test_uninstall_dry_run(temp_home, monkeypatch):
    calls: list[list[str]] = []

    def _fake_launchctl(args, check=False):
        calls.append(args)
        return _fake_cp(0)

    monkeypatch.setattr(installer_mod, "_launchctl", _fake_launchctl)
    outcome = installer_mod.uninstall(dry_run=True)
    assert outcome.ok is True
    assert calls == []


def test_resolve_executable_returns_argv(monkeypatch):
    monkeypatch.setattr(installer_mod.shutil, "which", lambda _name: None)
    argv = installer_mod.resolve_executable()
    assert isinstance(argv, list)
    assert argv[0].endswith("python") or "python" in argv[0]
    assert "cooldown.cli" in " ".join(argv)


def test_resolve_executable_prefers_cool_on_path(monkeypatch):
    monkeypatch.setattr(installer_mod.shutil, "which", lambda _name: "/opt/bin/cool")
    argv = installer_mod.resolve_executable()
    assert argv == ["/opt/bin/cool"]


def test_status_handles_missing_launchctl(temp_home, monkeypatch):
    def _boom(args, check=False):
        raise FileNotFoundError("no launchctl")

    monkeypatch.setattr(installer_mod, "_launchctl", _boom)
    st = installer_mod.status()
    assert st["installed"] is False
    assert st["pid"] is None
    assert st["label"] == "ai.cooldown.agent"


def test_status_parses_pid_and_exit(temp_home, monkeypatch):
    monkeypatch.setattr(
        installer_mod,
        "_launchctl",
        lambda args, check=False: _fake_cp(
            0,
            stdout=(
                "\tpid = 12345\n"
                "\tlast exit code = 0\n"
            ),
        ),
    )
    # Create a fake plist so installed=True
    installer_mod.plist_path().parent.mkdir(parents=True, exist_ok=True)
    installer_mod.plist_path().write_text("<plist/>", encoding="utf-8")
    st = installer_mod.status()
    assert st["installed"] is True
    assert st["pid"] == 12345
    assert st["last_exit_status"] == 0

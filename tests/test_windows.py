from __future__ import annotations

import sys
from pathlib import Path

import pytest

from snap_narrate import windows


def test_startup_command_uses_the_windowed_exe_even_from_the_cli(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / "SnapNarrate.exe").write_bytes(b"")
    cli = tmp_path / "snapnarrate-cli.exe"
    cli.write_bytes(b"")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(cli))
    command = windows.launch_command(tmp_path / "config.toml")
    assert command.startswith(f'"{tmp_path / "SnapNarrate.exe"}" run --config ')


def test_pre_05_startup_shortcut_is_swapped_for_the_run_key(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APPDATA", str(tmp_path))
    shortcut = tmp_path / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup" / "SnapNarrate.lnk"
    shortcut.parent.mkdir(parents=True)
    shortcut.write_bytes(b"old exe")

    class NoRegistry(windows.StartupManager):
        """Records instead of writing the real Run key."""

        enabled = 0

        def enable(self) -> None:
            self.enabled += 1
            windows._remove_legacy_startup_shortcut()

    manager = NoRegistry(tmp_path / "config.toml")
    assert manager.migrate_legacy() is True
    assert manager.enabled == 1 and not shortcut.exists()
    assert manager.migrate_legacy() is False  # nothing left to migrate

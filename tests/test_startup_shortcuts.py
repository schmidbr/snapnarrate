from __future__ import annotations

from pathlib import Path

from snap_narrate.shortcuts import ShortcutManager
from snap_narrate.startup import StartupManager


def test_shortcut_paths_have_expected_names() -> None:
    manager = ShortcutManager("SnapNarrate")
    assert manager.desktop_shortcut_path().name == "SnapNarrate.lnk"
    assert manager.startup_shortcut_path().name == "SnapNarrate.lnk"


class FakeShortcutManager:
    def __init__(self, path: Path) -> None:
        self._path = path

    def startup_shortcut_path(self) -> Path:
        return self._path

    def create_startup_shortcut(self, target: str, arguments: str, working_dir: str, icon_path: str | None = None) -> Path:  # noqa: ARG002
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text("fake shortcut", encoding="utf-8")
        return self._path

    def remove_shortcut(self, destination: Path) -> bool:  # noqa: ARG002
        if self._path.exists():
            self._path.unlink()
            return True
        return False


def test_startup_manager_enable_disable(tmp_path: Path) -> None:
    fake = FakeShortcutManager(tmp_path / "SnapNarrate.lnk")
    manager = StartupManager(
        shortcut_manager=fake,  # type: ignore[arg-type]
        target="C:\\snapnarrate.exe",
        arguments="run --config config.toml",
        working_dir="C:\\",
        icon_path=None,
    )

    assert manager.is_enabled() is False
    path = manager.enable()
    assert str(path).endswith("SnapNarrate.lnk")
    assert manager.is_enabled() is True
    assert manager.disable() is True
    assert manager.is_enabled() is False


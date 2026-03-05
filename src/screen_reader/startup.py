from __future__ import annotations

from pathlib import Path

from screen_reader.shortcuts import ShortcutManager


class StartupManager:
    def __init__(self, shortcut_manager: ShortcutManager, target: str, arguments: str, working_dir: str, icon_path: str | None = None) -> None:
        self.shortcut_manager = shortcut_manager
        self.target = target
        self.arguments = arguments
        self.working_dir = working_dir
        self.icon_path = icon_path

    def is_enabled(self) -> bool:
        return self.shortcut_manager.startup_shortcut_path().exists()

    def enable(self) -> Path:
        return self.shortcut_manager.create_startup_shortcut(
            target=self.target,
            arguments=self.arguments,
            working_dir=self.working_dir,
            icon_path=self.icon_path,
        )

    def disable(self) -> bool:
        return self.shortcut_manager.remove_shortcut(self.shortcut_manager.startup_shortcut_path())


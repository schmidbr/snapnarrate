"""Filesystem locations, aware of both source checkouts and frozen (PyInstaller) builds."""

from __future__ import annotations

import os
import sys
from pathlib import Path

APP_NAME = "SnapNarrate"


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def resource_path(relative: str) -> Path:
    """Path to a bundled read-only resource (icons, etc.)."""
    if is_frozen():
        base = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    else:
        base = Path(__file__).resolve().parents[2]
    return base / relative


def icon_path() -> Path:
    return resource_path("assets/snapnarrate.ico")


def user_data_dir() -> Path:
    appdata = os.getenv("APPDATA")
    root = Path(appdata) if appdata else Path.home() / "AppData" / "Roaming"
    return root / APP_NAME


def default_config_path() -> Path:
    """Config lookup order: a portable config.toml beside the exe, then %APPDATA%\\SnapNarrate."""
    if is_frozen():
        portable = Path(sys.executable).resolve().parent / "config.toml"
        if portable.exists():
            return portable
    return user_data_dir() / "config.toml"

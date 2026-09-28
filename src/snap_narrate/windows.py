"""Small Windows integrations: run-at-startup, sounds, single instance, DPI, dialogs."""

from __future__ import annotations

import ctypes
import logging
import os
import subprocess
import sys
from pathlib import Path

from snap_narrate.config import DEFAULT_CAPTURE_SOUND_NAME, WINDOWS_CAPTURE_SOUND_OPTIONS
from snap_narrate.paths import APP_NAME, is_frozen

logger = logging.getLogger("snap_narrate")

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
MUTEX_NAME = "SnapNarrateSingleInstance"  # also referenced by packaging/installer.iss (AppMutex)


def launch_command(config_path: Path) -> str:
    """Command line that starts the tray app with this config."""
    config = f'--config "{config_path.resolve()}"'
    if is_frozen():
        return f'"{sys.executable}" run {config}'
    pythonw = Path(sys.executable).with_name("pythonw.exe")
    interpreter = pythonw if pythonw.exists() else Path(sys.executable)
    return f'"{interpreter}" -m snap_narrate run {config}'


class StartupManager:
    """Run-at-login via the per-user registry Run key (no admin, no shortcut scripting)."""

    def __init__(self, config_path: Path, value_name: str = APP_NAME) -> None:
        self.config_path = config_path
        self.value_name = value_name

    def is_enabled(self) -> bool:
        import winreg

        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
                winreg.QueryValueEx(key, self.value_name)
                return True
        except FileNotFoundError:
            return False

    def enable(self) -> None:
        import winreg

        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            winreg.SetValueEx(key, self.value_name, 0, winreg.REG_SZ, launch_command(self.config_path))
        _remove_legacy_startup_shortcut()

    def disable(self) -> None:
        import winreg

        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
                winreg.DeleteValue(key, self.value_name)
        except FileNotFoundError:
            pass
        _remove_legacy_startup_shortcut()

    def set(self, enabled: bool) -> None:
        self.enable() if enabled else self.disable()


def _remove_legacy_startup_shortcut() -> None:
    """Versions before 0.5 used a Startup-folder shortcut; remove it so we never launch twice."""
    appdata = os.getenv("APPDATA")
    if not appdata:
        return
    legacy = Path(appdata) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup" / f"{APP_NAME}.lnk"
    try:
        legacy.unlink(missing_ok=True)
    except OSError as exc:
        logger.warning("event=legacy_shortcut_remove_failed error=%s", exc)


def play_capture_sound(name: str) -> None:
    filename = WINDOWS_CAPTURE_SOUND_OPTIONS.get(name, WINDOWS_CAPTURE_SOUND_OPTIONS[DEFAULT_CAPTURE_SOUND_NAME])
    if not filename:
        return
    try:
        import winsound

        path = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Media" / filename
        if path.exists():
            winsound.PlaySound(str(path), winsound.SND_FILENAME | winsound.SND_ASYNC | winsound.SND_NODEFAULT)
        else:
            winsound.PlaySound("SystemAsterisk", winsound.SND_ALIAS | winsound.SND_ASYNC)
    except Exception as exc:  # noqa: BLE001
        logger.warning("event=capture_sound_failed error=%s", exc)


def is_app_running(name: str = MUTEX_NAME) -> bool:
    """True if the tray app holds its single-instance mutex (without taking it ourselves)."""
    try:
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.OpenMutexW(0x00100000, False, name)  # SYNCHRONIZE
    except (AttributeError, OSError):
        return False
    if not handle:
        return False
    kernel32.CloseHandle(handle)
    return True


class SingleInstance:
    """Named mutex held for the app's lifetime. The installer uses it to detect a running copy."""

    def __init__(self, name: str = MUTEX_NAME) -> None:
        self._handle = None
        self.already_running = False
        try:
            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            self._handle = kernel32.CreateMutexW(None, False, name)
            self.already_running = ctypes.get_last_error() == 183  # ERROR_ALREADY_EXISTS
        except (AttributeError, OSError):
            pass


def enable_dpi_awareness() -> None:
    """Per-monitor DPI awareness so screen coordinates from Tk match physical capture pixels."""
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except (AttributeError, OSError):
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except (AttributeError, OSError):
            pass


def message_box(text: str, title: str = APP_NAME, error: bool = False) -> None:
    try:
        ctypes.windll.user32.MessageBoxW(None, text, title, 0x10 if error else 0x40)
    except (AttributeError, OSError):
        print(f"{title}: {text}", file=sys.stderr)


def open_path(path: Path) -> None:
    if hasattr(os, "startfile"):
        os.startfile(str(path))  # noqa: S606
    else:
        subprocess.Popen(["xdg-open", str(path)])  # noqa: S603,S607


def is_admin() -> bool:
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except (AttributeError, OSError):
        return False

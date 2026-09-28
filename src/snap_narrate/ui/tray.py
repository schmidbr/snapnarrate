"""System tray frontend."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import pystray
from PIL import Image, ImageDraw
from pystray import Menu, MenuItem

from snap_narrate import events
from snap_narrate.paths import icon_path
from snap_narrate.version import get_app_version

if TYPE_CHECKING:
    from snap_narrate.app import App

logger = logging.getLogger("snap_narrate")

_STATE_LABELS = {"idle": "Ready", "capturing": "Capturing…", "extracting": "Reading screen…", "speaking": "Speaking…"}


def load_icon() -> Image.Image:
    try:
        return Image.open(icon_path()).convert("RGBA")
    except Exception:  # noqa: BLE001
        image = Image.new("RGB", (64, 64), (35, 50, 70))
        draw = ImageDraw.Draw(image)
        draw.rectangle((16, 16, 48, 48), fill=(220, 220, 220))
        draw.rectangle((22, 22, 42, 42), fill=(70, 120, 180))
        return image


class Tray:
    def __init__(self, app: "App") -> None:
        self.app = app
        self.icon = pystray.Icon("SnapNarrate", load_icon(), "SnapNarrate", self._menu())
        self._unsubscribe = [
            app.bus.subscribe(events.NOTICE, lambda e: self.notify(e.data.get("message", ""))),
            app.bus.subscribe(events.STATUS, self._on_status),
        ]

    def start(self) -> None:
        self.icon.run_detached()

    def stop(self) -> None:
        for unsubscribe in self._unsubscribe:
            unsubscribe()
        self.icon.stop()

    def notify(self, message: str) -> None:
        if not message:
            return
        try:
            self.icon.notify(message, "SnapNarrate")
        except Exception:  # noqa: BLE001
            logger.debug("event=tray_notify_failed", exc_info=True)

    def _on_status(self, event: events.Event) -> None:
        state = _STATE_LABELS.get(str(event.data.get("state")), "Ready")
        if event.data.get("paused"):
            state = "Paused"
        self.icon.title = f"SnapNarrate: {state}"
        self.icon.update_menu()

    def _menu(self) -> Menu:
        app = self.app
        engine = lambda: app.engine  # noqa: E731 - engine can be rebuilt; always look it up

        return Menu(
            MenuItem(f"SnapNarrate {get_app_version()}", None, enabled=False),
            Menu.SEPARATOR,
            MenuItem("Capture Now", lambda: engine().capture("tray"), default=True),
            MenuItem("Capture Region", lambda: engine().capture_region("tray")),
            MenuItem("Stop Speaking", lambda: engine().stop_speaking()),
            MenuItem(
                "Capture Mode",
                Menu(
                    MenuItem("Full Screen", lambda: app.set_capture_mode("fullscreen"), radio=True,
                             checked=lambda _: engine().capture_mode == "fullscreen"),
                    MenuItem("Region", lambda: app.set_capture_mode("region"), radio=True,
                             checked=lambda _: engine().capture_mode == "region"),
                ),
            ),
            MenuItem("Pause", lambda: engine().toggle_pause(), checked=lambda _: engine().paused),
            Menu.SEPARATOR,
            MenuItem("Settings…", lambda: app.open_settings()),
            MenuItem("Run at Sign-in", lambda: app.toggle_startup(), checked=lambda _: app.startup_enabled()),
            MenuItem(
                "Tools",
                Menu(
                    MenuItem("Show Hotkeys", lambda: app.show_hotkeys()),
                    MenuItem("Test Voice", lambda: app.test_voice()),
                    MenuItem("Run Self-Test", lambda: app.run_self_test()),
                    MenuItem("Usage & Credits", lambda: app.show_usage()),
                    MenuItem("Open Logs", lambda: app.open_logs()),
                ),
            ),
            Menu.SEPARATOR,
            MenuItem("Exit", lambda: app.quit()),
        )

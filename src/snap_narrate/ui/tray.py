"""System tray icon and menu."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import pystray
from PIL import Image, ImageDraw
from pystray import Menu, MenuItem

from snap_narrate import events
from snap_narrate.hotkeys import keycaps
from snap_narrate.paths import icon_path
from snap_narrate.version import get_app_version

if TYPE_CHECKING:
    from snap_narrate.app import App

logger = logging.getLogger("snap_narrate")

_STATE_LABELS = {"idle": "Ready", "capturing": "Capturing…", "extracting": "Reading the screen…", "speaking": "Speaking…"}
VOLUME_PRESETS = (0.25, 0.5, 0.75, 1.0, 1.25, 1.5)


def load_icon() -> Image.Image:
    try:
        return Image.open(icon_path()).convert("RGBA")
    except Exception:  # noqa: BLE001
        image = Image.new("RGB", (64, 64), (35, 50, 70))
        draw = ImageDraw.Draw(image)
        draw.rectangle((16, 16, 48, 48), fill=(220, 220, 220))
        draw.rectangle((22, 22, 42, 42), fill=(70, 120, 180))
        return image


def _shortcut(spec: str) -> str:
    """Menu label suffix; Windows right-aligns text after a tab like an accelerator."""
    return f"\t{'+'.join(keycaps(spec))}" if spec else ""


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

    def _status_text(self) -> str:
        status = self.app.engine.status()
        if status.get("paused"):
            return "Paused"
        return _STATE_LABELS.get(str(status.get("state")), "Ready")

    def _on_status(self, _event: events.Event) -> None:
        self.icon.title = f"SnapNarrate: {self._status_text()}"
        self.icon.update_menu()

    def _menu(self) -> Menu:
        app = self.app
        engine = lambda: app.engine  # noqa: E731 - always look up the current engine
        cfg = lambda: app.cfg  # noqa: E731

        def volume_item(level: float) -> MenuItem:
            return MenuItem(
                f"{level:.0%}",
                lambda: app.set_volume(level),
                radio=True,
                checked=lambda _: abs(engine().volume - level) < 0.025,
            )

        return Menu(
            MenuItem(lambda _: f"SnapNarrate {get_app_version()}  ·  {self._status_text()}", None, enabled=False),
            Menu.SEPARATOR,
            MenuItem(lambda _: "Read Screen" + _shortcut(cfg().capture.hotkey), lambda: engine().capture("tray")),
            MenuItem(lambda _: "Read Region" + _shortcut(cfg().capture.region_hotkey), lambda: engine().capture_region("tray")),
            MenuItem(lambda _: "Stop Speaking" + _shortcut(cfg().capture.stop_hotkey), lambda: engine().stop_speaking()),
            Menu.SEPARATOR,
            MenuItem("Volume", Menu(lambda: (volume_item(level) for level in VOLUME_PRESETS))),
            MenuItem(
                "Capture",
                Menu(
                    MenuItem("Full Screen", lambda: app.set_capture_mode("fullscreen"), radio=True,
                             checked=lambda _: engine().capture_mode == "fullscreen"),
                    MenuItem("Region", lambda: app.set_capture_mode("region"), radio=True,
                             checked=lambda _: engine().capture_mode == "region"),
                ),
            ),  # fmt: skip
            MenuItem("Pause Reading", lambda: engine().toggle_pause(), checked=lambda _: engine().paused),
            Menu.SEPARATOR,
            MenuItem("Open SnapNarrate…", lambda: app.open_settings(), default=True),
            MenuItem(
                "Tools",
                Menu(
                    MenuItem("Test Voice", lambda: app.test_voice()),
                    MenuItem("Run Self-Test", lambda: app.run_self_test()),
                    MenuItem("Usage and Credits", lambda: app.show_usage()),
                    MenuItem("Show Shortcuts", lambda: app.show_hotkeys()),
                    MenuItem("Open Logs", lambda: app.open_logs()),
                ),
            ),
            Menu.SEPARATOR,
            MenuItem("Quit SnapNarrate", lambda: app.quit()),
        )

from __future__ import annotations

import time
from pathlib import Path
from types import SimpleNamespace

from snap_narrate.app import App
from snap_narrate.config import AppConfig


class SlowHotkeys:
    """Releasing every hotkey is slow, as when the hotkey thread is busy."""

    def __init__(self) -> None:
        self.bound: dict = {"initial": None}

    def bind(self, bindings: dict) -> dict:
        if not bindings:
            time.sleep(0.05)
        self.bound = dict(bindings)
        return {name: None for name in bindings}


def test_quick_pause_then_resume_ends_with_hotkeys_bound(tmp_path: Path) -> None:
    app = App(tmp_path / "config.toml")
    app.cfg = AppConfig()
    app.engine = SimpleNamespace(stop_speaking=lambda: None)  # type: ignore[assignment]
    app.hotkeys = SlowHotkeys()  # type: ignore[assignment]
    try:
        app.request_hotkey_pause(True)  # click a shortcut to record it...
        app.request_hotkey_pause(False)  # ...and press Esc straight away
        app._hotkey_ops.submit(lambda: None).result(timeout=2)
        assert app._hotkeys_paused is False
        assert "Read screen" in app.hotkeys.bound
    finally:
        app._hotkey_ops.shutdown()

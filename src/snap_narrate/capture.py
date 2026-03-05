from __future__ import annotations

import io
import time
from pathlib import Path

from mss import mss
from PIL import Image


class ScreenCapturer:
    def __init__(self, cooldown_ms: int, save_debug: bool = False, debug_dir: str = "debug_screenshots") -> None:
        self.cooldown_ms = cooldown_ms
        self.save_debug = save_debug
        self.debug_dir = Path(debug_dir)
        self._last_capture_ms = 0

    def can_capture(self) -> bool:
        now_ms = int(time.time() * 1000)
        return (now_ms - self._last_capture_ms) >= self.cooldown_ms

    def capture_png(self) -> bytes:
        if not self.can_capture():
            raise RuntimeError("Capture cooldown active")

        with mss() as sct:
            monitor = sct.monitors[1]
            shot = sct.grab(monitor)
            image = Image.frombytes("RGB", shot.size, shot.rgb)

        buf = io.BytesIO()
        image.save(buf, format="PNG")
        image_bytes = buf.getvalue()

        self._last_capture_ms = int(time.time() * 1000)
        if self.save_debug:
            self.debug_dir.mkdir(parents=True, exist_ok=True)
            timestamp = int(time.time())
            (self.debug_dir / f"capture_{timestamp}.png").write_bytes(image_bytes)

        return image_bytes

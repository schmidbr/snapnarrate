"""Screen capture. Produces compact JPEG/PNG bytes ready to send to a vision model."""

from __future__ import annotations

import io
import time
from pathlib import Path
from typing import Tuple

from PIL import Image

Bounds = Tuple[int, int, int, int]  # left, top, width, height in virtual-desktop pixels


class CaptureCooldown(RuntimeError):
    pass


class ScreenCapturer:
    def __init__(
        self,
        cooldown_ms: int = 1500,
        max_dimension: int = 1600,
        image_format: str = "jpeg",
        jpeg_quality: int = 85,
        debug_dir: Path | None = None,
    ) -> None:
        self.cooldown_ms = cooldown_ms
        self.max_dimension = max(int(max_dimension), 0)
        self.image_format = "png" if image_format == "png" else "jpeg"
        self.jpeg_quality = min(max(int(jpeg_quality), 1), 100)
        self.debug_dir = debug_dir
        self._last_capture = 0.0

    def fullscreen(self) -> bytes:
        """The monitor that contains the mouse cursor (usually the one the game is on)."""
        from mss import mss

        self._check_cooldown()
        with mss() as sct:
            monitor = _monitor_under_cursor(sct.monitors) or sct.monitors[1]
            return self._finish(sct.grab(monitor))

    def region(self, bounds: Bounds) -> bytes:
        from mss import mss

        left, top, width, height = (int(v) for v in bounds)
        if width <= 0 or height <= 0:
            raise ValueError("Invalid capture region")
        self._check_cooldown()
        with mss() as sct:
            return self._finish(sct.grab({"left": left, "top": top, "width": width, "height": height}))

    def encode(self, image: Image.Image) -> bytes:
        image = self._downscale(image.convert("RGB"))
        buffer = io.BytesIO()
        if self.image_format == "jpeg":
            image.save(buffer, format="JPEG", quality=self.jpeg_quality, optimize=True)
        else:
            image.save(buffer, format="PNG", optimize=True)
        return buffer.getvalue()

    def _check_cooldown(self) -> None:
        elapsed_ms = (time.monotonic() - self._last_capture) * 1000
        if self._last_capture and elapsed_ms < self.cooldown_ms:
            raise CaptureCooldown("Capture cooldown active; try again in a moment")

    def _finish(self, shot: object) -> bytes:
        image = Image.frombytes("RGB", shot.size, shot.rgb)  # type: ignore[attr-defined]
        data = self.encode(image)
        self._last_capture = time.monotonic()
        if self.debug_dir is not None:
            self.debug_dir.mkdir(parents=True, exist_ok=True)
            suffix = "jpg" if self.image_format == "jpeg" else "png"
            (self.debug_dir / f"capture_{int(time.time() * 1000)}.{suffix}").write_bytes(data)
        return data

    def _downscale(self, image: Image.Image) -> Image.Image:
        if self.max_dimension <= 0 or max(image.size) <= self.max_dimension:
            return image
        scale = self.max_dimension / float(max(image.size))
        size = (max(1, round(image.width * scale)), max(1, round(image.height * scale)))
        return image.resize(size, Image.Resampling.LANCZOS)


def normalize_bounds(x1: int, y1: int, x2: int, y2: int) -> Bounds:
    return min(x1, x2), min(y1, y2), abs(x2 - x1), abs(y2 - y1)


def is_valid_bounds(bounds: Bounds | None, min_px: int) -> bool:
    return bounds is not None and bounds[2] >= min_px and bounds[3] >= min_px


def _monitor_under_cursor(monitors: list[dict]) -> dict | None:
    try:
        import ctypes
        from ctypes import wintypes

        point = wintypes.POINT()
        if not ctypes.windll.user32.GetCursorPos(ctypes.byref(point)):
            return None
    except (AttributeError, OSError):
        return None
    for monitor in monitors[1:]:
        if (
            monitor["left"] <= point.x < monitor["left"] + monitor["width"]
            and monitor["top"] <= point.y < monitor["top"] + monitor["height"]
        ):
            return monitor
    return None

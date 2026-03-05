from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw


def project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def icon_asset_path() -> Path:
    return project_root() / "assets" / "snapnarrate.ico"


def load_tray_icon() -> Image.Image:
    icon_path = icon_asset_path()
    if icon_path.exists():
        try:
            return Image.open(icon_path).convert("RGBA")
        except Exception:  # noqa: BLE001
            pass
    return generated_fallback_icon()


def generated_fallback_icon() -> Image.Image:
    image = Image.new("RGB", (64, 64), color=(35, 50, 70))
    draw = ImageDraw.Draw(image)
    draw.rectangle((16, 16, 48, 48), fill=(220, 220, 220))
    draw.rectangle((22, 22, 42, 42), fill=(70, 120, 180))
    return image



from __future__ import annotations

import os
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


SELF_TEST_TITLE = "SnapNarrate Self-Test"
SELF_TEST_PARAGRAPHS = [
    (
        "The old observatory stood silent above the valley, its brass dome reflecting the last strip of evening light. "
        "When Mara pushed the door open, the room answered with a slow metallic sigh and the scent of rain-wet dust."
    ),
    (
        "On the central table she found a journal left open beside a cracked lens. The final entry warned that the machine "
        "did not predict the stars at all. It listened to them, and sometimes the stars whispered back."
    ),
]


def _font_candidates() -> list[Path]:
    fonts_dir = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts"
    return [
        fonts_dir / "segoeui.ttf",
        fonts_dir / "arial.ttf",
        fonts_dir / "calibri.ttf",
        fonts_dir / "tahoma.ttf",
    ]


def _load_font(size: int) -> ImageFont.ImageFont:
    for candidate in _font_candidates():
        if not candidate.exists():
            continue
        try:
            return ImageFont.truetype(str(candidate), size=size)
        except Exception:  # noqa: BLE001
            continue
    return ImageFont.load_default()


def _wrap_text(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont, max_width: int) -> list[str]:
    words = text.split()
    if not words:
        return [""]

    lines: list[str] = []
    current: list[str] = []
    for word in words:
        candidate = " ".join(current + [word])
        left, top, right, bottom = draw.textbbox((0, 0), candidate, font=font)
        if current and (right - left) > max_width:
            lines.append(" ".join(current))
            current = [word]
            continue
        current.append(word)

    if current:
        lines.append(" ".join(current))
    return lines


def create_self_test_image(width: int = 1400) -> Image.Image:
    """A synthetic "game journal" page with two known paragraphs, for end-to-end checks."""
    padding = max(48, width // 20)
    title_font = _load_font(max(28, width // 24))
    body_font = _load_font(max(22, width // 34))

    scratch_draw = ImageDraw.Draw(Image.new("RGB", (width, 200)))
    wrapped = [_wrap_text(scratch_draw, p, body_font, width - padding * 2) for p in SELF_TEST_PARAGRAPHS]
    _, _, _, title_height = scratch_draw.textbbox((0, 0), SELF_TEST_TITLE, font=title_font)
    _, _, _, line_height = scratch_draw.textbbox((0, 0), "Ag", font=body_font)
    paragraph_spacing = max(18, line_height // 2)
    line_spacing = max(12, line_height // 3)
    height = (
        padding * 2
        + title_height
        + paragraph_spacing
        + sum(len(lines) for lines in wrapped) * (line_height + line_spacing)
        + max(0, len(wrapped) - 1) * paragraph_spacing * 2
    )

    image = Image.new("RGB", (width, height), "#f8f5ef")
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle(
        (padding // 2, padding // 2, width - padding // 2, height - padding // 2),
        radius=max(16, padding // 3),
        fill="#fffdf8",
        outline="#d8cfbe",
        width=3,
    )
    draw.text((padding, padding), SELF_TEST_TITLE, fill="#1d1a17", font=title_font)
    y = padding + title_height + paragraph_spacing
    for index, lines in enumerate(wrapped):
        for line in lines:
            draw.text((padding, y), line, fill="#2a2622", font=body_font)
            y += line_height + line_spacing
        if index < len(wrapped) - 1:
            y += paragraph_spacing * 2
    return image

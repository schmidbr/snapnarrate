"""Visual language for SnapNarrate windows: Windows 11 fonts, icons and colors.

Colors are (light, dark) pairs; CustomTkinter picks one from the Windows app theme and
switches live when the user changes it.
"""

from __future__ import annotations

import tkinter.font as tkfont
from functools import lru_cache

import customtkinter as ctk

# Surfaces
WINDOW_BG = ("#f3f3f3", "#202020")
CARD_BG = ("#fbfbfb", "#2b2b2b")
CARD_BORDER = ("#e5e5e5", "#1f1f1f")
DIVIDER = ("#ebebeb", "#1f1f1f")
CONTROL_BG = ("#ffffff", "#2d2d2d")
CONTROL_HOVER = ("#f0f0f0", "#353535")
DROPDOWN_BG = ("#ededed", "#383838")  # dropdowns have no border, so they need a filled look
DROPDOWN_HOVER = ("#e2e2e2", "#414141")
CONTROL_BORDER = ("#d5d5d5", "#3d3d3d")
NAV_HOVER = ("#e9e9e9", "#2d2d2d")
NAV_SELECTED = ("#e4e4e4", "#2f2f2f")
FOOTER_BG = ("#ececec", "#1c1c1c")

# Text
TEXT = ("#1b1b1b", "#ffffff")
TEXT_SECONDARY = ("#616161", "#a8a8a8")
TEXT_ON_ACCENT = ("#ffffff", "#000000")

# Accent and status
ACCENT = ("#005fb8", "#60cdff")
ACCENT_HOVER = ("#1a6fc2", "#56b9e6")
# Filled selections carry white text, so they need a deeper blue than ACCENT in dark mode.
SELECTED = ("#005fb8", "#1b5fa6")
SELECTED_HOVER = ("#1a6fc2", "#2569b3")
DISABLED_BG = ("#e0e0e0", "#333333")
SUCCESS = ("#0f7b0f", "#6ccb5f")
WARNING = ("#9d5d00", "#fce100")
DANGER = ("#c42b1c", "#ff99a4")

# Segoe Fluent Icons / Segoe MDL2 Assets code points
ICONS = {
    "home": "\ue80f",
    "voice": "\ue767",
    "reading": "\ue890",
    "keyboard": "\ue765",
    "overlay": "\ue7f4",
    "advanced": "\ue713",
    "about": "\ue946",
    "play": "\ue768",
    "stop": "\ue71a",
    "search": "\ue721",
    "show": "\ue890",
    "hide": "\ued1a",
    "copy": "\ue8c8",
    "folder": "\ue838",
    "check": "\ue73e",
    "warning": "\ue7ba",
    "link": "\ue8a7",
    "refresh": "\ue72c",
    "rocket": "\ue7c8",
    "history": "\ue81c",
    "delete": "\ue74d",
}


@lru_cache(maxsize=1)
def _families() -> frozenset[str]:
    return frozenset(tkfont.families())


def _pick(*candidates: str) -> str:
    available = _families()
    return next((name for name in candidates if name in available), "Segoe UI")


def text_family() -> str:
    return _pick("Segoe UI Variable Text", "Segoe UI")


def strong_family() -> str:
    return _pick("Segoe UI Variable Text Semibold", "Segoe UI Semibold", "Segoe UI")


def display_family() -> str:
    return _pick("Segoe UI Variable Display", "Segoe UI")


def icon_family() -> str:
    return _pick("Segoe Fluent Icons", "Segoe MDL2 Assets")


class Fonts:
    """Type ramp modeled on Windows 11 (sizes in CustomTkinter units, scaled per monitor)."""

    def __init__(self) -> None:
        self.caption = ctk.CTkFont(family=text_family(), size=12)
        self.body = ctk.CTkFont(family=text_family(), size=14)
        self.body_strong = ctk.CTkFont(family=strong_family(), size=14)
        self.subtitle = ctk.CTkFont(family=display_family(), size=20, weight="bold")
        self.title = ctk.CTkFont(family=display_family(), size=28, weight="bold")
        self.icon = ctk.CTkFont(family=icon_family(), size=16)
        self.icon_small = ctk.CTkFont(family=icon_family(), size=12)
        self.icon_large = ctk.CTkFont(family=icon_family(), size=28)
        self.keycap = ctk.CTkFont(family=strong_family(), size=13)


def init() -> None:
    """Call once on the UI thread before creating CustomTkinter windows."""
    ctk.set_appearance_mode("system")
    ctk.set_default_color_theme("blue")

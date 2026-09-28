"""Subtitle overlay: shows the sentence being spoken over the game.

A borderless, always-on-top, click-through window. It appears over borderless/windowed
games; exclusive-fullscreen games draw above all desktop windows, so use borderless mode.
"""

from __future__ import annotations

import ctypes
import logging
import tkinter as tk
from typing import Callable

from snap_narrate import events
from snap_narrate.addons import AddonContext

logger = logging.getLogger("snap_narrate")

GWL_EXSTYLE = -20
WS_EX_TRANSPARENT, WS_EX_TOOLWINDOW, WS_EX_LAYERED, WS_EX_NOACTIVATE = 0x20, 0x80, 0x80000, 0x08000000


class SubtitleOverlay:
    name = "hud"

    def __init__(self) -> None:
        self._ctx: AddonContext | None = None
        self._win: tk.Toplevel | None = None
        self._label: tk.Label | None = None
        self._hide_job: str | None = None
        self._unsubscribe: list[Callable[[], None]] = []

    def start(self, ctx: AddonContext) -> None:
        if ctx.ui is None:
            raise RuntimeError("subtitle overlay needs the UI thread")
        self._ctx = ctx
        ctx.ui.call(self._create, timeout=5)
        self._unsubscribe = [
            ctx.bus.subscribe(events.SPEECH_CHUNK, lambda e: ctx.ui.submit(self._show, str(e.data.get("text", "")))),  # type: ignore[union-attr]
            ctx.bus.subscribe(events.SPEECH_IDLE, lambda _e: ctx.ui.submit(self._schedule_hide)),  # type: ignore[union-attr]
        ]

    def stop(self) -> None:
        for unsubscribe in self._unsubscribe:
            unsubscribe()
        self._unsubscribe.clear()
        if self._ctx is not None and self._ctx.ui is not None:
            self._ctx.ui.submit(self._destroy)

    def _destroy(self) -> None:
        # Drop widget references on the Tk thread so Tcl objects are freed where they were made.
        if self._win is not None:
            self._win.destroy()
        self._win = self._label = None
        self._hide_job = None

    # ---- Tk thread only ---------------------------------------------------------------

    def _create(self) -> None:
        assert self._ctx is not None and self._ctx.ui is not None
        hud = self._ctx.config.hud
        win = tk.Toplevel(self._ctx.ui.root)
        win.overrideredirect(True)
        win.attributes("-topmost", True)
        # Shown once and then faded in/out with alpha: re-showing a window can take focus
        # from the game, changing opacity never does.
        win.attributes("-alpha", 0.0)
        win.geometry("1x1+0+0")
        win.configure(bg="#111111")
        label = tk.Label(
            win,
            text="",
            fg="#ffffff",
            bg="#111111",
            font=("Segoe UI", hud.font_size),
            justify="center",
            padx=24,
            pady=12,
        )
        label.pack()
        self._win, self._label = win, label
        win.update_idletasks()
        self._make_click_through(win)

    @staticmethod
    def _make_click_through(win: tk.Toplevel) -> None:
        try:
            user32 = ctypes.windll.user32
            hwnd = user32.GetParent(win.winfo_id()) or win.winfo_id()
            style = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
            user32.SetWindowLongW(
                hwnd, GWL_EXSTYLE, style | WS_EX_LAYERED | WS_EX_TRANSPARENT | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE
            )
        except (AttributeError, OSError):
            logger.debug("event=hud_click_through_unavailable", exc_info=True)

    def _show(self, text: str) -> None:
        if self._win is None or self._label is None or self._ctx is None or not text:
            return
        if self._hide_job is not None:
            self._win.after_cancel(self._hide_job)
            self._hide_job = None
        screen_w, screen_h = self._win.winfo_screenwidth(), self._win.winfo_screenheight()
        width = int(screen_w * 0.7)
        self._label.config(text=text, wraplength=width - 48)
        self._win.update_idletasks()
        height = self._label.winfo_reqheight()
        x = (screen_w - width) // 2
        y = int(screen_h * 0.06) if self._ctx.config.hud.position == "top" else screen_h - height - int(screen_h * 0.1)
        self._win.geometry(f"{width}x{height}+{x}+{y}")
        self._win.attributes("-alpha", self._ctx.config.hud.opacity)
        self._win.attributes("-topmost", True)

    def _schedule_hide(self) -> None:
        if self._win is None or self._ctx is None:
            return
        if self._hide_job is not None:
            self._win.after_cancel(self._hide_job)
        self._hide_job = self._win.after(self._ctx.config.hud.linger_ms, self._hide)

    def _hide(self) -> None:
        self._hide_job = None
        if self._win is not None:
            self._win.attributes("-alpha", 0.0)

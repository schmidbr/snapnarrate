"""Subtitle overlay: shows the line being spoken over the game, with a segmented progress bar.

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
from snap_narrate.progress import ProgressTracker

logger = logging.getLogger("snap_narrate")

GWL_EXSTYLE = -20
WS_EX_TRANSPARENT, WS_EX_TOOLWINDOW, WS_EX_LAYERED, WS_EX_NOACTIVATE = 0x20, 0x80, 0x80000, 0x08000000

BG = "#111111"
BAR_HEIGHT = 6
BAR_GAP = 4  # pixels between segments
PAD_X, PAD_Y = 24, 12
COLOR_FILL = "#2fd4ff"
COLOR_TRACK = "#3a3a3a"  # a chunk whose audio exists
COLOR_ESTIMATED = "#2a2a2a"  # a chunk still being voiced; width is an estimate
COLOR_PENDING = "#1e1e1e"  # the rest of the passage is still being read

PROGRESS_TOPICS = (events.NARRATION_PLAN, events.SPEECH_CHUNK, events.SPEECH_PROGRESS)


class SubtitleOverlay:
    name = "hud"

    def __init__(self) -> None:
        self._ctx: AddonContext | None = None
        self._win: tk.Toplevel | None = None
        self._label: tk.Label | None = None
        self._bar: tk.Canvas | None = None
        self._tracker = ProgressTracker()
        self._bar_width = 0  # known from the geometry we set; Tk reports it only after a redraw
        self._hide_job: str | None = None
        self._unsubscribe: list[Callable[[], None]] = []

    def start(self, ctx: AddonContext) -> None:
        if ctx.ui is None:
            raise RuntimeError("subtitle overlay needs the UI thread")
        self._ctx = ctx
        ui = ctx.ui
        ui.call(self._create, timeout=5)
        topics = {events.SPEECH_CHUNK, events.SPEECH_IDLE}
        if ctx.config.hud.progress_bar:
            topics.update(PROGRESS_TOPICS)
        self._unsubscribe = [ctx.bus.subscribe(topic, lambda e: ui.submit(self._on_event, e)) for topic in topics]

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
        self._win = self._label = self._bar = None
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
        win.configure(bg=BG)
        label = tk.Label(win, text="", fg="#ffffff", bg=BG, font=("Segoe UI", hud.font_size), justify="center")
        label.pack(padx=PAD_X, pady=(PAD_Y, PAD_Y if not hud.progress_bar else 8))
        if hud.progress_bar:
            self._bar = tk.Canvas(win, height=BAR_HEIGHT, bg=BG, highlightthickness=0, bd=0)
            self._bar.pack(fill=tk.X, padx=PAD_X, pady=(0, PAD_Y))
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

    def _on_event(self, event: events.Event) -> None:
        changed = self._tracker.handle(event) if event.topic in PROGRESS_TOPICS else False
        if event.topic == events.SPEECH_CHUNK:
            self._show(str(event.data.get("text", "")))
        elif event.topic == events.SPEECH_IDLE:
            self._schedule_hide()
        if changed:
            self._draw_bar()

    def _show(self, text: str) -> None:
        if self._win is None or self._label is None or self._ctx is None or not text:
            return
        if self._hide_job is not None:
            self._win.after_cancel(self._hide_job)
            self._hide_job = None
        screen_w, screen_h = self._win.winfo_screenwidth(), self._win.winfo_screenheight()
        width = int(screen_w * 0.7)
        self._bar_width = width - 2 * PAD_X
        self._label.config(text=text, wraplength=width - 2 * PAD_X)
        self._win.update_idletasks()
        height = self._win.winfo_reqheight()
        x = (screen_w - width) // 2
        y = int(screen_h * 0.06) if self._ctx.config.hud.position == "top" else screen_h - height - int(screen_h * 0.1)
        self._win.geometry(f"{width}x{height}+{x}+{y}")
        self._win.attributes("-alpha", self._ctx.config.hud.opacity)
        self._win.attributes("-topmost", True)

    def _draw_bar(self) -> None:
        if self._bar is None:
            return
        canvas = self._bar
        canvas.delete("all")
        width = self._bar_width
        if width <= 0:  # nothing shown yet; the first speech chunk sets the size
            return
        state = self._tracker.state()
        for segment in state.segments:
            x0 = segment.start * width
            x1 = max(x0 + 1, segment.end * width - BAR_GAP)
            color = COLOR_ESTIMATED if segment.estimated else COLOR_TRACK
            canvas.create_rectangle(x0, 0, x1, BAR_HEIGHT, fill=color, width=0)
            if segment.fill > 0:
                canvas.create_rectangle(x0, 0, x0 + (x1 - x0) * segment.fill, BAR_HEIGHT, fill=COLOR_FILL, width=0)
        if state.pending_from is not None:
            canvas.create_rectangle(state.pending_from * width, 0, width, BAR_HEIGHT, fill=COLOR_PENDING, width=0)

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

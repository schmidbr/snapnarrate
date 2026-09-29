"""Click-and-drag region picker covering the whole virtual desktop."""

from __future__ import annotations

import ctypes
import tkinter as tk
from concurrent.futures import Future

from snap_narrate.capture import Bounds, normalize_bounds
from snap_narrate.ui.tk_thread import TkThread


def _virtual_screen() -> tuple[int, int, int, int]:
    metrics = ctypes.windll.user32.GetSystemMetrics
    return metrics(76), metrics(77), metrics(78), metrics(79)  # SM_[XY]VIRTUALSCREEN, SM_C[XY]VIRTUALSCREEN


def select_region(ui: TkThread, timeout: float = 120.0) -> Bounds | None:
    """Show the picker and wait for a selection. Returns absolute virtual-desktop bounds,
    or None if cancelled (Esc / right-click) or left alone for `timeout` seconds, which
    also closes the overlay. Must not be called on the Tk thread."""
    result: Future[Bounds | None] = Future()
    ui.submit(_open_picker, ui, result, timeout)
    try:
        return result.result(timeout=timeout + 10)  # the picker times itself out; this is a backstop
    except TimeoutError:
        return None


def _open_picker(ui: TkThread, result: Future[Bounds | None], timeout: float) -> None:
    left, top, width, height = _virtual_screen()
    win = tk.Toplevel(ui.root)
    win.overrideredirect(True)
    win.attributes("-topmost", True)
    win.attributes("-alpha", 0.25)
    win.configure(bg="black", cursor="crosshair")
    win.geometry(f"{width}x{height}+{left}+{top}")

    canvas = tk.Canvas(win, bg="black", highlightthickness=0, cursor="crosshair")
    canvas.pack(fill=tk.BOTH, expand=True)
    state: dict[str, int | None] = {"x": None, "y": None, "rect": None}

    def finish(bounds: Bounds | None) -> None:
        if result.done():
            return
        win.after_cancel(expiry)
        win.destroy()
        # Make sure the overlay is gone from the screen before anyone grabs pixels.
        if ui.root is not None:
            ui.root.update()
        if not result.done():
            result.set_result(bounds)

    def on_press(event: tk.Event) -> None:
        state["x"], state["y"] = event.x_root, event.y_root
        if state["rect"] is not None:
            canvas.delete(state["rect"])
        state["rect"] = canvas.create_rectangle(event.x, event.y, event.x, event.y, outline="#2fd4ff", width=2)

    def on_drag(event: tk.Event) -> None:
        if state["rect"] is None or state["x"] is None or state["y"] is None:
            return
        canvas.coords(state["rect"], state["x"] - left, state["y"] - top, event.x_root - left, event.y_root - top)

    def on_release(event: tk.Event) -> None:
        if state["x"] is None or state["y"] is None:
            return
        finish(normalize_bounds(state["x"], state["y"], event.x_root, event.y_root))

    canvas.bind("<ButtonPress-1>", on_press)
    canvas.bind("<B1-Motion>", on_drag)
    canvas.bind("<ButtonRelease-1>", on_release)
    canvas.bind("<ButtonPress-3>", lambda _e: finish(None))
    win.bind("<Escape>", lambda _e: finish(None))
    win.protocol("WM_DELETE_WINDOW", lambda: finish(None))
    # Left alone (the player alt-tabbed away): close, rather than dim every monitor and swallow clicks.
    expiry = win.after(int(timeout * 1000), lambda: finish(None))
    win.lift()
    win.focus_force()

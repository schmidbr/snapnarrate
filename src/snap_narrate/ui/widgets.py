"""Reusable CustomTkinter building blocks for SnapNarrate windows.

Widgets never touch Tk from a background thread: slow work runs on a worker thread and
hands its result back through `post`, which queues a callback onto the UI thread.
"""

from __future__ import annotations

import threading
import tkinter as tk
import webbrowser
from typing import Any, Callable, Sequence

import customtkinter as ctk

from snap_narrate.hotkeys import MODIFIER_VKS, keycaps, parse_hotkey, spec_from_keys
from snap_narrate.ui import theme as t

Post = Callable[[Callable[[], None]], None]
Options = Sequence[tuple[str, str]]  # (stored value, label shown to the user)


def run_in_background(post: Post, work: Callable[[], Any], done: Callable[[Any], None]) -> None:
    """Run work() off the UI thread, then done(result or exception) on it."""

    def worker() -> None:
        try:
            result: Any = work()
        except Exception as exc:  # noqa: BLE001
            result = exc
        post(lambda: done(result))

    threading.Thread(target=worker, daemon=True).start()


# ---- layout -------------------------------------------------------------------------------


class Card(ctk.CTkFrame):
    """A group of settings, each on its own rounded tile (the Windows 11 Settings look)."""

    def __init__(self, master: Any, fonts: t.Fonts) -> None:
        super().__init__(master, fg_color="transparent")
        self.fonts = fonts

    def _tile(self) -> ctk.CTkFrame:
        tile = ctk.CTkFrame(self, fg_color=t.CARD_BG, border_color=t.CARD_BORDER, border_width=1, corner_radius=6)
        tile.pack(fill="x", pady=(0, 3))
        tile.grid_columnconfigure(0, weight=1)
        return tile

    def add(self, title: str, description: str, build: Callable[[Any], Any], note: str = "") -> Any:
        """A tile with a title/description on the left and the control built by build(tile) on the right."""
        tile = self._tile()
        text = ctk.CTkFrame(tile, fg_color="transparent")
        text.grid(row=0, column=0, sticky="w", padx=(18, 16), pady=12)
        ctk.CTkLabel(text, text=title, font=self.fonts.body, text_color=t.TEXT, anchor="w", height=22).pack(anchor="w")
        detail = " · ".join(part for part in (description, note) if part)
        if detail:
            ctk.CTkLabel(
                text, text=detail, font=self.fonts.caption, text_color=t.TEXT_SECONDARY, anchor="w",
                justify="left", wraplength=420, height=18,
            ).pack(anchor="w")  # fmt: skip
        control = build(tile)
        control.grid(row=0, column=1, sticky="e", padx=(0, 18), pady=10)
        return control

    def add_full(self, build: Callable[[Any], Any]) -> Any:
        """A tile whose content spans its whole width."""
        tile = self._tile()
        control = build(tile)
        control.grid(row=0, column=0, sticky="ew", padx=18, pady=12)
        return control


def section(parent: Any, fonts: t.Fonts, title: str | None = None) -> Card:
    """A titled card, packed into a page."""
    if title:
        ctk.CTkLabel(parent, text=title, font=fonts.body_strong, text_color=t.TEXT, anchor="w").pack(
            fill="x", padx=4, pady=(18, 6)
        )
    card = Card(parent, fonts)
    card.pack(fill="x", pady=(0 if title else 12, 0))
    return card


# ---- controls -----------------------------------------------------------------------------


def switch(parent: Any, var: tk.BooleanVar, state: str = "normal") -> ctk.CTkSwitch:
    return ctk.CTkSwitch(
        parent, text="", variable=var, onvalue=True, offvalue=False, width=44,
        progress_color=t.ACCENT, button_color=("#5d5d5d", "#d0d0d0"), button_hover_color=("#4d4d4d", "#e0e0e0"),
        state=state,
    )  # fmt: skip


class LabeledOption(ctk.CTkOptionMenu):
    """Dropdown that shows friendly labels but stores raw values in `var`."""

    def __init__(self, parent: Any, var: tk.StringVar, options: Options, fonts: t.Fonts, width: int = 260, state: str = "normal") -> None:
        self._var = var
        self._choices = list(options)
        current = var.get()
        if current not in {value for value, _ in self._choices}:
            self._choices.append((current, current or "(none)"))  # keep an unknown value selectable
        self._by_label = {label: value for value, label in self._choices}
        super().__init__(
            parent, values=[label for _, label in self._choices], width=width, command=self._picked,
            font=fonts.body, dropdown_font=fonts.body, fg_color=t.DROPDOWN_BG, button_color=t.DROPDOWN_BG,
            button_hover_color=t.DROPDOWN_HOVER, text_color=t.TEXT, dropdown_fg_color=t.CARD_BG,
            dropdown_hover_color=t.CONTROL_HOVER, dropdown_text_color=t.TEXT, dynamic_resizing=False, state=state,
        )  # fmt: skip
        self._sync()
        var.trace_add("write", lambda *_: self._sync())

    def _picked(self, label: str) -> None:
        self._var.set(self._by_label.get(label, label))

    def _sync(self) -> None:
        value = self._var.get()
        label = next((lbl for val, lbl in self._choices if val == value), value)
        if self.get() != label:
            self.set(label)


class Segmented(ctk.CTkSegmentedButton):
    """A small set of mutually exclusive choices shown side by side."""

    def __init__(self, parent: Any, var: tk.StringVar, options: Options, fonts: t.Fonts, state: str = "normal") -> None:
        self._var = var
        self._choices = list(options)
        super().__init__(
            parent, values=[label for _, label in options], command=self._picked, font=fonts.body,
            selected_color=t.SELECTED, selected_hover_color=t.SELECTED_HOVER, unselected_color=t.DROPDOWN_BG,
            unselected_hover_color=t.DROPDOWN_HOVER, fg_color=t.DROPDOWN_BG, text_color=("#1b1b1b", "#ffffff"),
            state=state,
        )  # fmt: skip
        self._sync()
        var.trace_add("write", lambda *_: self._sync())

    def _picked(self, label: str) -> None:
        self._var.set(next((value for value, lbl in self._choices if lbl == label), label))

    def _sync(self) -> None:
        label = next((lbl for value, lbl in self._choices if value == self._var.get()), None)
        if label is not None and self.get() != label:
            self.set(label)


class TextField(ctk.CTkFrame):
    """Entry with optional unit suffix and show/hide toggle for secrets."""

    def __init__(
        self, parent: Any, var: tk.StringVar, fonts: t.Fonts, width: int = 260, secret: bool = False,
        placeholder: str = "", unit: str = "", state: str = "normal",
    ) -> None:  # fmt: skip
        super().__init__(parent, fg_color="transparent")
        self._secret = secret
        self.entry = ctk.CTkEntry(
            self, textvariable=var, width=width, font=fonts.body, show="•" if secret else "",
            placeholder_text=placeholder or None, fg_color=t.CONTROL_BG, border_color=t.CONTROL_BORDER,
            text_color=t.TEXT, border_width=1, corner_radius=4, state=state,
        )  # fmt: skip
        self.entry.pack(side="left")
        if secret:
            self._eye = ctk.CTkButton(
                self, text=t.ICONS["show"], font=fonts.icon_small, width=30, height=28, fg_color="transparent",
                hover_color=t.CONTROL_HOVER, text_color=t.TEXT_SECONDARY, command=self._toggle,
            )  # fmt: skip
            self._eye.pack(side="left", padx=(4, 0))
        if unit:
            ctk.CTkLabel(self, text=unit, font=fonts.caption, text_color=t.TEXT_SECONDARY).pack(side="left", padx=(8, 0))

    def _toggle(self) -> None:
        hidden = self.entry.cget("show") == "•"
        self.entry.configure(show="" if hidden else "•")
        self._eye.configure(text=t.ICONS["hide"] if hidden else t.ICONS["show"])


class Slider(ctk.CTkFrame):
    """Slider bound to a string var (so it shares storage with text fields), with a value label."""

    def __init__(
        self, parent: Any, var: tk.StringVar, fonts: t.Fonts, low: float, high: float, step: float,
        fmt: Callable[[float], str], integer: bool, state: str = "normal",
    ) -> None:  # fmt: skip
        super().__init__(parent, fg_color="transparent")
        self._var, self._fmt, self._integer = var, fmt, integer
        self._label = ctk.CTkLabel(self, text="", font=fonts.body, text_color=t.TEXT_SECONDARY, width=64, anchor="e")
        self._label.pack(side="left", padx=(0, 10))
        self._slider = ctk.CTkSlider(
            self, from_=low, to=high, number_of_steps=max(1, round((high - low) / step)), width=220,
            command=self._moved, progress_color=t.ACCENT, button_color=t.ACCENT, button_hover_color=t.ACCENT_HOVER,
            state=state,
        )  # fmt: skip
        self._slider.pack(side="left")
        self._sync()
        var.trace_add("write", lambda *_: self._sync())

    def _moved(self, value: float) -> None:
        self._var.set(str(int(round(value))) if self._integer else f"{value:.2f}")

    def _sync(self) -> None:
        try:
            value = float(self._var.get())
        except ValueError:
            return
        if abs(self._slider.get() - value) > 1e-9:
            self._slider.set(value)
        self._label.configure(text=self._fmt(value))


class LinkLabel(ctk.CTkLabel):
    def __init__(self, parent: Any, text: str, url: str, fonts: t.Fonts) -> None:
        super().__init__(parent, text=text, font=fonts.caption, text_color=t.ACCENT, cursor="hand2")
        self.bind("<Button-1>", lambda _e: webbrowser.open(url))


def button(parent: Any, text: str, command: Callable[[], None], fonts: t.Fonts, accent: bool = False, icon: str = "", width: int = 0) -> ctk.CTkButton:
    label = f"{icon}  {text}" if icon and text else (icon or text)
    return ctk.CTkButton(
        parent, text=label, command=command, width=width or (0 if text else 32), height=32, corner_radius=4,
        font=fonts.body, fg_color=t.ACCENT if accent else t.CONTROL_BG,
        hover_color=t.ACCENT_HOVER if accent else t.CONTROL_HOVER,
        text_color=t.TEXT_ON_ACCENT if accent else t.TEXT, border_width=0 if accent else 1,
        border_color=t.CONTROL_BORDER,
    )  # fmt: skip


# ---- hotkey recorder ----------------------------------------------------------------------


class HotkeyRecorder(ctk.CTkFrame):
    """Shows a shortcut as key caps. Click it, then press a new combination (Esc cancels)."""

    def __init__(
        self, parent: Any, var: tk.StringVar, fonts: t.Fonts, validate: Callable[[str], str | None],
        on_recording: Callable[[bool], None] | None = None, state: str = "normal", optional: bool = False,
    ) -> None:  # fmt: skip
        super().__init__(parent, fg_color="transparent")
        self._var, self._fonts, self._validate, self._on_recording = var, fonts, validate, on_recording
        self._optional = optional
        self._held: set[str] = set()
        self._recording = False
        self._bindings: list[tuple[str, str]] = []
        line = ctk.CTkFrame(self, fg_color="transparent")
        line.pack(anchor="e")
        if optional:
            ctk.CTkButton(
                line, text="Clear", width=56, height=32, corner_radius=4, font=fonts.caption, fg_color="transparent",
                hover_color=t.CONTROL_HOVER, text_color=t.TEXT_SECONDARY, command=lambda: var.set(""), state=state,
            ).pack(side="left", padx=(0, 6))  # fmt: skip
        self._caps = ctk.CTkButton(
            line, text="", width=200, height=32, corner_radius=4, font=fonts.keycap, fg_color=t.CONTROL_BG,
            hover_color=t.CONTROL_HOVER, text_color=t.TEXT, border_width=1, border_color=t.CONTROL_BORDER,
            command=self.start, state=state,
        )  # fmt: skip
        self._caps.pack(side="left")
        # Only takes space when there is something to say, so rows stay evenly spaced.
        self._error = ctk.CTkLabel(self, text="", font=fonts.caption, text_color=t.DANGER, anchor="e", height=16)
        self._render()
        var.trace_add("write", lambda *_: self._render())

    def _render(self) -> None:
        if self._recording:
            self._caps.configure(text="Press a shortcut…  (Esc to cancel)", border_color=t.ACCENT)
            return
        spec = self._var.get()
        self._caps.configure(text="  +  ".join(keycaps(spec)) if spec else "Not set", border_color=t.CONTROL_BORDER)
        if spec:
            error = self._validate(spec)
        else:
            error = None if self._optional else "Choose a shortcut"
        self._error.configure(text=error or "")
        if error and not self._error.winfo_ismapped():
            self._error.pack(anchor="e")
        elif not error and self._error.winfo_ismapped():
            self._error.pack_forget()

    def start(self) -> None:
        if self._recording:
            return
        self._recording, self._held = True, set()
        top = self.winfo_toplevel()
        for sequence, handler in (("<KeyPress>", self._press), ("<KeyRelease>", self._release)):
            self._bindings.append((sequence, top.bind(sequence, handler, add="+")))
        top.focus_force()
        if self._on_recording:
            self._on_recording(True)  # let the app pause its global hotkeys so pressing them here is safe
        self._render()

    def _stop(self) -> None:
        top = self.winfo_toplevel()
        for sequence, funcid in self._bindings:
            top.unbind(sequence, funcid)
        self._bindings.clear()
        self._recording = False
        if self._on_recording:
            self._on_recording(False)
        self._render()

    def _press(self, event: tk.Event) -> str:
        vk = int(event.keycode)
        if vk in MODIFIER_VKS:
            self._held.add(MODIFIER_VKS[vk])
            return "break"
        if vk == 0x1B and not self._held:  # Esc alone cancels
            self._stop()
            return "break"
        spec = spec_from_keys(self._held, vk)
        if spec:
            self._stop()
            self._var.set(spec)
        return "break"

    def _release(self, event: tk.Event) -> str:
        self._held.discard(MODIFIER_VKS.get(int(event.keycode), ""))
        return "break"


def hotkey_problem(spec: str, others: Sequence[str]) -> str | None:
    """Why a shortcut can't be used, or None if it's fine."""
    try:
        mods, vk = parse_hotkey(spec)
    except ValueError as exc:
        return str(exc)
    standalone_ok = 0x70 <= vk <= 0x87 or vk in (0x13, 0x91, 0x2C)  # F-keys, Pause, Scroll Lock, Print Screen
    if mods == 0 and not standalone_ok:
        return "Add Ctrl, Alt, Shift or Win so it doesn't fire while typing"
    if spec in others:
        return "Already used by another SnapNarrate shortcut"
    return None

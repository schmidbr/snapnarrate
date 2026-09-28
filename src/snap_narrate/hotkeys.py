"""Global hotkeys via the Win32 RegisterHotKey API.

Unlike a low-level keyboard hook, RegisterHotKey only reports the exact combinations we
register: no keystroke stream is observed, no admin rights are needed, and antivirus
heuristics have nothing keylogger-like to flag.
"""

from __future__ import annotations

import ctypes
import logging
import threading
from ctypes import wintypes
from typing import Callable

logger = logging.getLogger("snap_narrate")

MOD_ALT, MOD_CONTROL, MOD_SHIFT, MOD_WIN, MOD_NOREPEAT = 0x1, 0x2, 0x4, 0x8, 0x4000
WM_HOTKEY, WM_QUIT, WM_APP = 0x0312, 0x0012, 0x8000
_WM_APPLY = WM_APP + 1

_MODIFIERS = {"ctrl": MOD_CONTROL, "control": MOD_CONTROL, "alt": MOD_ALT, "shift": MOD_SHIFT, "win": MOD_WIN}
_NAMED_KEYS = {
    "space": 0x20, "enter": 0x0D, "return": 0x0D, "tab": 0x09, "esc": 0x1B, "escape": 0x1B,
    "backspace": 0x08, "insert": 0x2D, "ins": 0x2D, "delete": 0x2E, "del": 0x2E,
    "home": 0x24, "end": 0x23, "pageup": 0x21, "pgup": 0x21, "pagedown": 0x22, "pgdn": 0x22,
    "up": 0x26, "down": 0x28, "left": 0x25, "right": 0x27,
    "printscreen": 0x2C, "prtsc": 0x2C, "pause": 0x13, "scrolllock": 0x91,
    "`": 0xC0, "-": 0xBD, "=": 0xBB, "[": 0xDB, "]": 0xDD, "\\": 0xDC, ";": 0xBA, "'": 0xDE,
    ",": 0xBC, ".": 0xBE, "/": 0xBF,
}  # fmt: skip


def parse_hotkey(spec: str) -> tuple[int, int]:
    """'ctrl+shift+n' -> (modifier flags, virtual-key code). Raises ValueError if invalid."""
    parts = [p.strip().lower() for p in spec.replace(" ", "").split("+") if p.strip()]
    if not parts:
        raise ValueError("Hotkey is empty")
    mods, key = 0, None
    for part in parts:
        if part in _MODIFIERS:
            mods |= _MODIFIERS[part]
            continue
        if key is not None:
            raise ValueError(f"Hotkey {spec!r} has more than one non-modifier key")
        key = _vk(part)
    if key is None:
        raise ValueError(f"Hotkey {spec!r} needs a key besides modifiers")
    return mods, key


def _vk(name: str) -> int:
    if len(name) == 1 and (name.isalpha() or name.isdigit()):
        return ord(name.upper())
    if name in _NAMED_KEYS:
        return _NAMED_KEYS[name]
    if name.startswith("f") and name[1:].isdigit() and 1 <= int(name[1:]) <= 24:
        return 0x70 + int(name[1:]) - 1
    if name.startswith("num") and name[3:].isdigit() and len(name) == 4:
        return 0x60 + int(name[3:])
    raise ValueError(f"Unknown key {name!r}")


class HotkeyManager:
    """Owns a message-loop thread. `bind` replaces all hotkeys at once and reports which
    ones registered (another app may already own a combination)."""

    def __init__(self) -> None:
        self._thread: threading.Thread | None = None
        self._thread_id = 0
        self._ready = threading.Event()
        self._lock = threading.Lock()
        self._pending: dict[str, tuple[str, Callable[[], None]]] = {}
        self._applied = threading.Event()
        self._results: dict[str, str | None] = {}
        self._callbacks: dict[int, Callable[[], None]] = {}

    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(target=self._loop, name="snapnarrate-hotkeys", daemon=True)
        self._thread.start()
        self._ready.wait(timeout=5)

    def bind(self, bindings: dict[str, tuple[str, Callable[[], None]]]) -> dict[str, str | None]:
        """bindings: {name: (hotkey spec, callback)}. Returns {name: None if OK else error}."""
        self.start()
        with self._lock:
            self._pending = dict(bindings)
            self._applied.clear()
            ctypes.windll.user32.PostThreadMessageW(self._thread_id, _WM_APPLY, 0, 0)
            self._applied.wait(timeout=5)
            return dict(self._results)

    def stop(self) -> None:
        if self._thread is not None and self._thread_id:
            ctypes.windll.user32.PostThreadMessageW(self._thread_id, WM_QUIT, 0, 0)
            self._thread.join(timeout=2)
        self._thread = None

    def _loop(self) -> None:
        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32
        msg = wintypes.MSG()
        # Force creation of this thread's message queue before announcing readiness.
        user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, 0)
        self._thread_id = kernel32.GetCurrentThreadId()
        self._ready.set()

        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            if msg.message == WM_HOTKEY:
                callback = self._callbacks.get(int(msg.wParam))
                if callback is not None:
                    # Run off the message loop so a slow action never delays other hotkeys.
                    threading.Thread(target=self._safe_call, args=(callback,), daemon=True).start()
            elif msg.message == _WM_APPLY:
                self._apply(user32)
        self._unregister_all(user32)

    def _apply(self, user32: object) -> None:
        self._unregister_all(user32)
        results: dict[str, str | None] = {}
        for hotkey_id, (name, (spec, callback)) in enumerate(self._pending.items(), start=1):
            try:
                mods, vk = parse_hotkey(spec)
            except ValueError as exc:
                results[name] = str(exc)
                continue
            if user32.RegisterHotKey(None, hotkey_id, mods | MOD_NOREPEAT, vk):  # type: ignore[attr-defined]
                self._callbacks[hotkey_id] = callback
                results[name] = None
            else:
                results[name] = f"{spec} is already in use by another app"
        self._results = results
        logger.info("event=hotkeys_bound results=%s", results)
        self._applied.set()

    def _unregister_all(self, user32: object) -> None:
        for hotkey_id in list(self._callbacks):
            user32.UnregisterHotKey(None, hotkey_id)  # type: ignore[attr-defined]
        self._callbacks.clear()

    @staticmethod
    def _safe_call(callback: Callable[[], None]) -> None:
        try:
            callback()
        except Exception:  # noqa: BLE001
            logger.exception("event=hotkey_callback_failed")

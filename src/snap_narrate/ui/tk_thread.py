"""One thread owns Tk. Every window (settings, region picker, HUD) is created through it.

Tkinter is not thread-safe; creating Tk roots from several threads is what made the old
region selector and settings window unstable when used together.
"""

from __future__ import annotations

import gc
import logging
import queue
import threading
import tkinter as tk
from concurrent.futures import Future
from typing import Any, Callable

logger = logging.getLogger("snap_narrate")


class TkThread:
    def __init__(self) -> None:
        self._calls: queue.Queue[tuple[Callable[..., Any], tuple[Any, ...], Future[Any]]] = queue.Queue()
        self._ready = threading.Event()
        self.root: tk.Tk | None = None
        self._thread = threading.Thread(target=self._run, name="snapnarrate-ui", daemon=True)
        self._thread.start()
        self._ready.wait(timeout=10)

    def submit(self, fn: Callable[..., Any], *args: Any) -> Future[Any]:
        """Run fn(*args) on the Tk thread. Safe to call from any thread, including the Tk thread."""
        future: Future[Any] = Future()
        if threading.current_thread() is self._thread:
            self._invoke(fn, args, future)
        else:
            self._calls.put((fn, args, future))
        return future

    def call(self, fn: Callable[..., Any], *args: Any, timeout: float | None = None) -> Any:
        return self.submit(fn, *args).result(timeout=timeout)

    def stop(self) -> None:
        if self.root is not None:
            self.submit(self.root.quit)
        self._thread.join(timeout=2)

    def _run(self) -> None:
        self.root = tk.Tk()
        self.root.withdraw()
        self._ready.set()
        self._pump()
        self.root.mainloop()
        try:
            self.root.destroy()
        except tk.TclError:
            pass
        # The Tcl interpreter must be freed on the thread that created it, or Tcl aborts
        # with "async handler deleted by the wrong thread" when Python exits.
        self.root = None
        gc.collect()

    def _pump(self) -> None:
        while True:
            try:
                fn, args, future = self._calls.get_nowait()
            except queue.Empty:
                break
            self._invoke(fn, args, future)
        assert self.root is not None
        self.root.after(25, self._pump)

    @staticmethod
    def _invoke(fn: Callable[..., Any], args: tuple[Any, ...], future: Future[Any]) -> None:
        if not future.set_running_or_notify_cancel():
            return
        try:
            future.set_result(fn(*args))
        except BaseException as exc:  # noqa: BLE001
            logger.exception("event=ui_call_failed fn=%s", getattr(fn, "__name__", fn))
            future.set_exception(exc)

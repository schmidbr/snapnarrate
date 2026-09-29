"""Narration history: what SnapNarrate read, kept on this PC so it can be re-read or replayed.

The recorder listens on the event bus, so every way of starting a narration (hotkey, tray,
local API) is captured without the engine knowing about history. Entries are stored newest
first in a small JSON file next to the config.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable

from snap_narrate import events
from snap_narrate.events import EventBus

logger = logging.getLogger("snap_narrate")

# Narrations that aren't worth keeping: diagnostics, and replays of existing entries.
SKIPPED_SOURCES = {"self_test", "test_voice", "replay"}


@dataclass
class HistoryEntry:
    id: str
    time: float  # unix seconds
    source: str  # e.g. "hotkey:fullscreen", "tray:region", "api"
    text: str
    run_id: str = ""  # app run that produced it; cached audio only exists within that run
    session: int = 0

    @property
    def trigger(self) -> str:
        """'Region', 'Full screen', 'API'... for display."""
        kind = self.source.split(":")[-1]
        return {"fullscreen": "Full screen", "region": "Region", "api": "API"}.get(kind, kind.replace("_", " ").title())


class History:
    def __init__(self, path: Path | None, max_items: int = 100, enabled: bool = True) -> None:
        self.path = path
        self.max_items = max(1, max_items)
        self.enabled = enabled
        self.run_id = ""
        self._lock = threading.Lock()
        self._entries: list[HistoryEntry] = []
        self._pending: dict[int, dict[str, Any]] = {}
        self._by_session: dict[int, str] = {}
        self._version = 0
        self._known_stamp: tuple[int, int] | None = None  # (mtime, size) of the file we last read or wrote
        self._unsubscribe: list[Callable[[], None]] = []
        with self._lock:
            self._load_locked()

    # ---- reading ----------------------------------------------------------------------

    @property
    def version(self) -> int:
        """Changes whenever entries change; lets UIs refresh cheaply."""
        return self._version

    def entries(self) -> list[HistoryEntry]:
        with self._lock:
            return list(self._entries)

    def latest(self) -> HistoryEntry | None:
        with self._lock:
            return self._entries[0] if self._entries else None

    def get(self, entry_id: str) -> HistoryEntry | None:
        with self._lock:
            return next((e for e in self._entries if e.id == entry_id), None)

    def refresh(self) -> None:
        """Pick up changes another process (the running app, or a standalone settings
        window) saved to the file."""
        with self._lock:
            self._reload_if_changed_locked()

    # ---- editing ----------------------------------------------------------------------

    def configure(self, max_items: int, enabled: bool) -> None:
        with self._lock:
            self._reload_if_changed_locked()
            self.max_items = max(1, max_items)
            self.enabled = enabled
            if len(self._entries) > self.max_items:
                del self._entries[self.max_items :]
                self._changed_locked()

    def delete(self, entry_id: str) -> None:
        with self._lock:
            self._reload_if_changed_locked()
            self._entries = [e for e in self._entries if e.id != entry_id]
            self._changed_locked()

    def clear(self) -> None:
        with self._lock:
            self._reload_if_changed_locked()
            self._entries.clear()
            self._changed_locked()

    # ---- recording --------------------------------------------------------------------

    def attach(self, bus: EventBus) -> None:
        self.detach()
        self._unsubscribe = [
            bus.subscribe(events.NARRATION_STARTED, self._on_started),
            bus.subscribe(events.NARRATION_TEXT, self._on_text),
            bus.subscribe(events.NARRATION_FINISHED, self._on_finished),
        ]

    def detach(self) -> None:
        for unsubscribe in self._unsubscribe:
            unsubscribe()
        self._unsubscribe = []

    def _on_started(self, event: events.Event) -> None:
        with self._lock:
            self._pending[int(event.data["session"])] = {"source": str(event.data.get("source", "")), "text": "", "time": event.ts}
            # Only the most recent few sessions can still receive text; forget older ones.
            for stale in sorted(self._pending)[:-8]:
                self._pending.pop(stale, None)

    def _on_text(self, event: events.Event) -> None:
        session = int(event.data["session"])
        text = str(event.data.get("text", ""))
        with self._lock:
            if session in self._pending:
                self._pending[session]["text"] = text
            entry_id = self._by_session.get(session) if event.data.get("final") else None
            if not entry_id:
                return
            self._reload_if_changed_locked()
            entry = next((e for e in self._entries if e.id == entry_id), None)
            if entry is None or entry.text == text:
                return
            entry.text = text  # the full passage arrived after speech started
            self._changed_locked()

    def _on_finished(self, event: events.Event) -> None:
        session = int(event.data["session"])
        with self._lock:
            pending = self._pending.get(session)
            if (
                not self.enabled
                or pending is None
                or event.data.get("status") != "played"
                or pending["source"] in SKIPPED_SOURCES
                or not pending["text"].strip()
            ):
                return
            self._reload_if_changed_locked()  # don't undo a clear or delete made in another window
            entry = HistoryEntry(
                id=f"{int(pending['time'] * 1000)}-{session}",
                time=pending["time"],
                source=pending["source"],
                text=pending["text"],
                run_id=self.run_id,
                session=session,
            )
            self._entries.insert(0, entry)
            del self._entries[self.max_items :]
            self._by_session[session] = entry.id
            for stale in sorted(self._by_session)[:-16]:
                self._by_session.pop(stale, None)
            self._changed_locked()

    # ---- storage ----------------------------------------------------------------------
    # Everything below runs with self._lock held, so reads, edits and writes never interleave.

    def _changed_locked(self) -> None:
        self._version += 1
        self._save_locked()

    def _stamp(self) -> tuple[int, int] | None:
        try:
            stat = self.path.stat() if self.path is not None else None
        except OSError:
            return None
        return (stat.st_mtime_ns, stat.st_size) if stat is not None else None

    def _reload_if_changed_locked(self) -> None:
        if self.path is not None and self._stamp() != self._known_stamp:
            self._load_locked()
            self._version += 1

    def _load_locked(self) -> None:
        self._known_stamp = self._stamp()
        if self.path is None or self._known_stamp is None:
            self._entries = []
            return
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            fields = HistoryEntry.__dataclass_fields__
            self._entries = [HistoryEntry(**{k: v for k, v in item.items() if k in fields}) for item in raw.get("entries", [])]
            del self._entries[self.max_items :]
        except Exception as exc:  # noqa: BLE001 - a corrupt file must not stop the app
            logger.warning("event=history_load_failed error=%s", exc)
            self._entries = []

    def _save_locked(self) -> None:
        if self.path is None:
            return
        data = {"version": 1, "entries": [asdict(e) for e in self._entries]}
        # Per-process temp name: the app and a standalone settings window may save at once.
        tmp = self.path.with_name(f"{self.path.name}.{os.getpid()}.tmp")
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
            os.replace(tmp, self.path)
            self._known_stamp = self._stamp()
        except OSError as exc:
            logger.warning("event=history_save_failed error=%s", exc)


def format_when(timestamp: float, now: float | None = None) -> str:
    """'Today 7:05 PM', 'Yesterday 11:40 AM', 'Sep 21 3:02 PM'."""
    now_local = time.localtime(now if now is not None else time.time())
    then = time.localtime(timestamp)
    clock = time.strftime("%I:%M %p", then).lstrip("0")
    days = (time.mktime(now_local[:3] + (0, 0, 0, 0, 0, -1)) - time.mktime(then[:3] + (0, 0, 0, 0, 0, -1))) / 86400
    if round(days) == 0:
        return f"Today {clock}"
    if round(days) == 1:
        return f"Yesterday {clock}"
    return time.strftime("%b %d", then).replace(" 0", " ") + f" {clock}"

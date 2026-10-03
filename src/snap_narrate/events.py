"""A tiny thread-safe publish/subscribe bus.

The engine publishes what it is doing; frontends (tray, HUD, local API, future Game Bar
widget) subscribe. Handlers run synchronously on the publishing thread, so they must be
quick: hand real work off to your own thread or UI loop.
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable

# Topics. Payload keys are documented in docs/ADDONS.md.
STATUS = "status"  # {"state": "idle|capturing|extracting|speaking", "paused": bool, "capture_mode": str}
NOTICE = "notice"  # {"message": str, "level": "info|warning|error"}
CAPTURE = "capture"  # {"source": "fullscreen|region|api|self_test", "bytes": int, "capture_ms": int}
NARRATION_STARTED = "narration.started"  # {"session": int}
NARRATION_TEXT = "narration.text"  # {"session": int, "text": str, "final": bool} full text known so far
# The chunks this narration will be spoken in, as character counts, in playback order.
# final=False means more chunks may be appended (the rest of the passage is still being read).
NARRATION_PLAN = "narration.plan"  # {"session": int, "chunk_chars": [int], "final": bool}
NARRATION_FINISHED = "narration.finished"  # {"session": int, "status": str, "message": str, "chars": int, "timings": {...}}
SPEECH_CHUNK = "speech.chunk"  # {"session": int, "index": int, "text": str, "duration": float} a chunk started playing
SPEECH_PROGRESS = "speech.progress"  # {"session": int, "index": int, "position": float, "duration": float} ~10x/second
SPEECH_IDLE = "speech.idle"  # {} playback queue drained or stopped

ALL = "*"

Handler = Callable[["Event"], None]


@dataclass(frozen=True)
class Event:
    topic: str
    data: dict[str, Any] = field(default_factory=dict)
    ts: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {"topic": self.topic, "data": self.data, "ts": self.ts}


class EventBus:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._handlers: dict[str, list[Handler]] = {}
        self._logger = logging.getLogger("snap_narrate")

    def subscribe(self, topic: str, handler: Handler) -> Callable[[], None]:
        """Subscribe to one topic, or ALL. Returns an unsubscribe function."""
        with self._lock:
            self._handlers.setdefault(topic, []).append(handler)

        def unsubscribe() -> None:
            with self._lock:
                handlers = self._handlers.get(topic, [])
                if handler in handlers:
                    handlers.remove(handler)

        return unsubscribe

    def publish(self, topic: str, **data: Any) -> Event:
        event = Event(topic=topic, data=data)
        with self._lock:
            handlers = list(self._handlers.get(topic, [])) + list(self._handlers.get(ALL, []))
        for handler in handlers:
            try:
                handler(event)
            except Exception:  # noqa: BLE001 - one bad subscriber must not break the engine
                self._logger.exception("event=handler_failed topic=%s", topic)
        return event

    def notice(self, message: str, level: str = "info") -> None:
        self.publish(NOTICE, message=message, level=level)

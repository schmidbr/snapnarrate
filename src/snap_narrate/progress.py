"""Segmented playback progress, computed from speech events.

One segment per spoken chunk. Finished segments are full, the playing one fills from real
playback position, and upcoming ones are sized from the voice's measured speaking rate
until their audio exists. While the rest of the passage is still being read, a dim tail
marks "more coming". Pure logic with no UI, so any frontend (the subtitle overlay, or a
widget consuming the local API's event stream) can render it.
"""

from __future__ import annotations

from dataclasses import dataclass

from snap_narrate import events

DEFAULT_CHARS_PER_SEC = 15.0  # typical ElevenLabs narration pace, until measured
RATE_SMOOTHING = 0.3  # weight of each newly measured chunk in the running speaking rate
PENDING_TAIL = 0.15  # share of the bar reserved for "more coming" while the plan is open


@dataclass(frozen=True)
class Segment:
    start: float  # 0..1 along the bar
    end: float
    fill: float  # 0..1 of this segment already heard
    estimated: bool  # width is an estimate: this chunk's audio does not exist yet


@dataclass(frozen=True)
class BarState:
    segments: tuple[Segment, ...] = ()
    pending_from: float | None = None  # where the "more coming" tail starts, if any


class ProgressTracker:
    def __init__(self, chars_per_sec: float = DEFAULT_CHARS_PER_SEC) -> None:
        self.chars_per_sec = chars_per_sec
        self._reset(None)

    def _reset(self, session: int | None) -> None:
        self.session = session
        self._chars: list[int] = []
        self._final = True
        self._durations: dict[int, float] = {}
        self._current = -1
        self._position = 0.0

    def handle(self, event: events.Event) -> bool:
        """Feed any event; returns True if the bar changed."""
        data = event.data
        session = data.get("session")
        if event.topic == events.NARRATION_PLAN:
            if session != self.session:
                self._reset(session)
            self._chars = [int(c) for c in data.get("chunk_chars", [])]
            self._final = bool(data.get("final", True))
            return True
        if event.topic == events.SPEECH_CHUNK:
            if session != self.session:
                self._reset(session)  # speech without a plan (e.g. a voice preview): a single segment
            index, duration = int(data.get("index", 0)), float(data.get("duration", 0.0))
            chars = len(str(data.get("text", "")))
            while len(self._chars) <= index:
                self._chars.append(chars)
            self._durations[index] = duration
            self._current, self._position = index, 0.0
            self._learn_rate(chars, duration)
            return True
        if event.topic == events.SPEECH_PROGRESS and session == self.session:
            index, duration = int(data.get("index", 0)), float(data.get("duration", 0.0))
            self._durations[index] = duration
            self._current = index
            self._position = min(float(data.get("position", 0.0)), duration)
            return True
        return False

    def _learn_rate(self, chars: int, duration: float) -> None:
        if chars <= 0 or duration <= 0.2:
            return
        measured = chars / duration
        self.chars_per_sec += RATE_SMOOTHING * (measured - self.chars_per_sec)

    def state(self) -> BarState:
        if not self._chars:
            return BarState()
        widths = [self._durations.get(i, chars / self.chars_per_sec) for i, chars in enumerate(self._chars)]
        total = sum(widths) or 1.0
        span = 1.0 if self._final else 1.0 - PENDING_TAIL
        segments: list[Segment] = []
        cursor = 0.0
        for i, width in enumerate(widths):
            end = cursor + span * width / total
            if i < self._current:
                fill = 1.0
            elif i == self._current and self._durations.get(i):
                fill = min(self._position / self._durations[i], 1.0)
            else:
                fill = 0.0
            segments.append(Segment(cursor, end, fill, estimated=i not in self._durations))
            cursor = end
        return BarState(tuple(segments), None if self._final else cursor)

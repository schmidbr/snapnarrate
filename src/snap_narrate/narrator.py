"""Screenshot -> text -> voice.

A narration runs inside a Session. The first chunk is synthesized and started on the
calling thread (so the caller learns time-to-first-audio); the rest is synthesized in the
background and queued. Cancelling the session stops the background work at the next step
and the audio player drops anything it still tries to queue.
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Callable

from snap_narrate import events
from snap_narrate.audio import AudioPlayer
from snap_narrate.config import AppConfig
from snap_narrate.events import EventBus
from snap_narrate.providers.base import SpeechProvider, VisionProvider
from snap_narrate.text import (
    TextDeduper,
    adaptive_initial_chars,
    align_remaining,
    followup_chunks,
    head_chunk,
    normalize_text,
    remaining_after,
    should_continue,
)

logger = logging.getLogger("snap_narrate")


class Session:
    def __init__(self, session_id: int) -> None:
        self.id = session_id
        self._cancelled = threading.Event()

    def cancel(self) -> None:
        self._cancelled.set()

    @property
    def cancelled(self) -> bool:
        return self._cancelled.is_set()


@dataclass
class NarratorSettings:
    min_block_chars: int = 140
    dedup_enabled: bool = True
    dedup_similarity_threshold: float = 0.95
    retry_count: int = 2
    retry_backoff_ms: int = 700
    speech_first_enabled: bool = True
    initial_chunk_chars: int = 220
    followup_chunk_chars: int = 650
    followup_min_chars: int = 60

    @classmethod
    def from_config(cls, cfg: AppConfig) -> "NarratorSettings":
        return cls(
            min_block_chars=cfg.filter.min_block_chars,
            dedup_enabled=cfg.dedup.enabled,
            dedup_similarity_threshold=cfg.dedup.similarity_threshold,
            retry_count=cfg.playback.retry_count,
            retry_backoff_ms=cfg.playback.retry_backoff_ms,
            speech_first_enabled=cfg.playback.speech_first_enabled,
            initial_chunk_chars=cfg.playback.initial_chunk_chars,
            followup_chunk_chars=cfg.playback.followup_chunk_chars,
            followup_min_chars=cfg.playback.followup_min_chars,
        )


@dataclass
class Timings:
    extract_ms: int = 0
    tts_ms: int = 0
    total_ms: int = 0  # time to first audio


@dataclass
class NarrationResult:
    status: str  # "played" | "skipped" | "failed" | "cancelled"
    message: str
    chars: int = 0
    text: str = ""
    timings: Timings = field(default_factory=Timings)

    @property
    def played(self) -> bool:
        return self.status == "played"


def _spawn_thread(fn: Callable[[], None]) -> None:
    threading.Thread(target=fn, name="snapnarrate-continuation", daemon=True).start()


class Narrator:
    def __init__(
        self,
        vision: VisionProvider,
        speech: SpeechProvider,
        player: AudioPlayer,
        settings: NarratorSettings | None = None,
        bus: EventBus | None = None,
        sleep_fn: Callable[[float], None] = time.sleep,
        time_fn: Callable[[], float] = time.perf_counter,
        spawn: Callable[[Callable[[], None]], None] = _spawn_thread,
    ) -> None:
        self.vision = vision
        self.speech = speech
        self.player = player
        self.settings = settings or NarratorSettings()
        self.bus = bus
        self.deduper = TextDeduper(self.settings.dedup_similarity_threshold)
        self._sleep = sleep_fn
        self._now = time_fn
        self._spawn = spawn
        # on_audio(session_id, audio, text, output_format) for every chunk handed to the player,
        # then on_audio_complete(session_id) once a session's whole passage has been handed over.
        self.on_audio: Callable[[int, bytes, str, str], None] | None = None
        self.on_audio_complete: Callable[[int], None] | None = None

    # ---- public API -------------------------------------------------------------------

    def narrate(self, image: bytes, session: Session, profile: str = "default", dedup: bool = True) -> NarrationResult:
        start = self._now()
        if self.settings.speech_first_enabled:
            result = self._narrate_speech_first(image, session, profile, dedup, start)
            if result is not None:
                return result
        return self._narrate_full(image, session, profile, dedup, start)

    def speak_text(self, text: str, session: Session) -> NarrationResult:
        """Speak text supplied directly (API, addons, voice test). No extraction or dedup."""
        start = self._now()
        normalized = normalize_text(text)
        if not normalized:
            return NarrationResult("skipped", "Nothing to say")
        self._publish_text(session, normalized, final=True)
        return self._speak(self._split(normalized), session, start, extract_ms=0, fast_first=True, text=normalized)

    # ---- pipelines --------------------------------------------------------------------

    def _narrate_full(self, image: bytes, session: Session, profile: str, dedup: bool, start: float) -> NarrationResult:
        extract = self.vision.extract(image, profile)
        extract_ms = self._ms_since(start)
        text = normalize_text(extract.text)

        skip = self._skip_reason(text, extract.dropped_reason, dedup)
        if skip:
            return NarrationResult("skipped", skip, len(text), text, Timings(extract_ms, 0, self._ms_since(start)))
        if session.cancelled:
            return NarrationResult("cancelled", "Cancelled", len(text), text)

        self._publish_text(session, text, final=True)
        read = text if dedup and self.settings.dedup_enabled else None
        return self._speak(self._split(text), session, start, extract_ms, fast_first=False, text=text, read=read)

    def _narrate_speech_first(
        self, image: bytes, session: Session, profile: str, dedup: bool, start: float
    ) -> NarrationResult | None:
        extract = self.vision.extract_first(image, profile)
        extract_ms = self._ms_since(start)
        initial_text = normalize_text(extract.text)
        chunk_chars = adaptive_initial_chars(initial_text, extract.more_text_likely, self.settings.initial_chunk_chars)
        first = head_chunk(initial_text, chunk_chars)

        # Judge the whole first read, not just its first line: a short opening line such as a
        # speaker name is a fine (and fast) first chunk when real text follows it.
        if not first or len(initial_text) < min(self.settings.min_block_chars, 80):
            logger.info("event=speech_first_fallback reason=short_first_read chars=%s", len(initial_text))
            return None
        # Dedup on the whole first read: two dialogues can open with the same speaker line.
        if dedup and self.settings.dedup_enabled and self.deduper.is_repeat(initial_text):
            return NarrationResult(
                "skipped", "Already read this text", len(initial_text), initial_text, Timings(extract_ms, 0, self._ms_since(start))
            )
        if session.cancelled:
            return NarrationResult("cancelled", "Cancelled", len(first), first)

        logger.info(
            "event=speech_first_chunk source_chars=%s chunk_chars=%s more_text_likely=%s",
            len(initial_text),
            chunk_chars,
            extract.more_text_likely,
        )
        self._publish_text(session, initial_text, final=False)

        def remaining_chunks() -> list[str]:
            chunk_size = self.settings.followup_chunk_chars
            if not should_continue(extract.more_text_likely, initial_text, self.settings.initial_chunk_chars):
                # The first read already holds the whole passage: speak the rest of it, no second read.
                self._publish_text(session, initial_text, final=True)
                rest = remaining_after(initial_text, first)
                logger.info("event=speech_first_single_read remaining_chars=%s", len(rest))
                return followup_chunks(rest, chunk_size)
            full = normalize_text(self.vision.extract(image, profile).text)
            if not full:  # the second read found nothing: fall back to what the first read had
                full = initial_text
            self._publish_text(session, full, final=True)
            rest, exact = align_remaining(full, first)
            logger.info("event=speech_first_second_read full_chars=%s remaining_chars=%s exact=%s", len(full), len(rest), exact)
            return followup_chunks(rest, chunk_size, 1 if exact else self.settings.followup_min_chars)

        read = initial_text if dedup and self.settings.dedup_enabled else None
        return self._speak([first], session, start, extract_ms, fast_first=True, text=initial_text, more=remaining_chunks, read=read)

    # ---- speaking ---------------------------------------------------------------------

    def _speak(
        self,
        chunks: list[str],
        session: Session,
        start: float,
        extract_ms: int,
        fast_first: bool,
        text: str,
        more: Callable[[], list[str]] | None = None,
        read: str | None = None,
    ) -> NarrationResult:
        """Synthesize and start the first chunk now; synthesize and queue the rest in the background.
        `read` is remembered for dedup once audio actually starts."""
        if not chunks:
            return NarrationResult("skipped", "Nothing to say", 0, text)

        tts_start = self._now()
        audio = self._synthesize(chunks[0], session, fast=fast_first)
        tts_ms = self._ms_since(tts_start)
        if audio is None:
            status = "cancelled" if session.cancelled else "failed"
            message = "Cancelled" if session.cancelled else "Text-to-speech failed after retries"
            return NarrationResult(status, message, len(text), text, Timings(extract_ms, tts_ms, self._ms_since(start)))
        if session.cancelled:
            return NarrationResult("cancelled", "Cancelled", len(text), text)

        self._publish_plan(session, chunks, final=more is None)
        self.player.play(audio, session.id, chunks[0])
        if read is not None:
            self.deduper.remember(read)
        self._remember(session, audio, chunks[0])
        timings = Timings(extract_ms, tts_ms, self._ms_since(start))

        if len(chunks) > 1 or more is not None:
            self._spawn(lambda: self._continue(session, chunks, more))
        else:
            self._audio_complete(session)
        return NarrationResult("played", "Narration started", len(text), text, timings)

    def _continue(self, session: Session, planned: list[str], more: Callable[[], list[str]] | None) -> None:
        """Speak planned[1:] (planned[0] is already playing), plus whatever `more` adds."""
        chunks = planned[1:]
        try:
            if more is not None:
                if session.cancelled:
                    logger.info("event=continuation_cancelled session=%s remaining=unknown", session.id)
                    return
                extra = more()
                chunks = chunks + extra
                self._publish_plan(session, planned + extra, final=True)
            for index, chunk in enumerate(chunks):
                if session.cancelled:
                    logger.info("event=continuation_cancelled session=%s remaining=%s", session.id, len(chunks) - index)
                    return
                audio = self._synthesize(chunk, session)
                if audio is None:
                    if not session.cancelled:
                        logger.warning("event=continuation_failed reason=tts_retry_exhausted session=%s", session.id)
                    return
                if not self.player.queue(audio, session.id, chunk):
                    logger.info("event=continuation_dropped session=%s", session.id)
                    return
                self._remember(session, audio, chunk)
            logger.info("event=continuation_completed session=%s chunks=%s", session.id, len(chunks))
            self._audio_complete(session)
        except Exception as exc:  # noqa: BLE001
            logger.warning("event=continuation_failed session=%s error=%s", session.id, exc)

    def _synthesize(self, text: str, session: Session, fast: bool = False) -> bytes | None:
        attempts = self.settings.retry_count + 1
        for attempt in range(attempts):
            if session.cancelled:
                return None
            try:
                return self.speech.synthesize(text, fast=fast)
            except ValueError:
                raise  # configuration problem (missing key/voice): retrying will not help
            except Exception as exc:  # noqa: BLE001
                logger.warning("event=tts_failure attempt=%s error=%s", attempt + 1, exc)
                if attempt + 1 < attempts:
                    self._sleep((self.settings.retry_backoff_ms / 1000.0) * (2**attempt))
        return None

    # ---- helpers ----------------------------------------------------------------------

    def _skip_reason(self, text: str, dropped_reason: str | None, dedup: bool) -> str | None:
        if not text:
            return f"No narrative text found ({dropped_reason})" if dropped_reason else "No narrative text found"
        if len(text) < self.settings.min_block_chars:
            return f"Text too short to narrate ({len(text)} chars)"
        if dedup and self.settings.dedup_enabled and self.deduper.is_repeat(text):
            return "Already read this text"
        return None

    def _split(self, text: str) -> list[str]:
        """First chunk sized for fast start, then larger follow-up chunks. Nothing is dropped."""
        first = head_chunk(text, self.settings.initial_chunk_chars)
        rest = remaining_after(text, first) if first else text
        return [first, *followup_chunks(rest, self.settings.followup_chunk_chars, 1)] if first else []

    def _remember(self, session: Session, audio: bytes, text: str) -> None:
        if self.on_audio is not None:
            try:
                self.on_audio(session.id, audio, text, self.speech.output_format)
            except Exception:  # noqa: BLE001
                logger.exception("event=audio_callback_failed")

    def _audio_complete(self, session: Session) -> None:
        if self.on_audio_complete is not None:
            try:
                self.on_audio_complete(session.id)
            except Exception:  # noqa: BLE001
                logger.exception("event=audio_callback_failed")

    def _publish_plan(self, session: Session, chunks: list[str], final: bool) -> None:
        if self.bus is not None:
            self.bus.publish(events.NARRATION_PLAN, session=session.id, chunk_chars=[len(c) for c in chunks], final=final)

    def _publish_text(self, session: Session, text: str, final: bool) -> None:
        if self.bus is not None:
            self.bus.publish(events.NARRATION_TEXT, session=session.id, text=text, final=final)

    def _ms_since(self, t0: float) -> int:
        return int(round((self._now() - t0) * 1000))

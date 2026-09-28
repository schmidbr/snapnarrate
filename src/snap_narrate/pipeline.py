from __future__ import annotations

import logging
import re
import threading
import time
from difflib import SequenceMatcher
from typing import Callable, Protocol

from snap_narrate.models import ExtractResult, PipelineResult, PipelineTimings
from snap_narrate.text_processing import TextDeduper, normalize_text


class VisionExtractor(Protocol):
    def extract_narrative_text(self, image_bytes: bytes, game_profile: str = "default") -> ExtractResult:
        ...


class TTSProvider(Protocol):
    def synthesize(self, text: str) -> bytes:
        ...


class AudioPlayer(Protocol):
    def play(self, audio_bytes: bytes) -> None:
        ...


class NarrationPipeline:
    def __init__(
        self,
        extractor: VisionExtractor,
        tts: TTSProvider,
        player: AudioPlayer,
        min_block_chars: int,
        dedup_enabled: bool,
        dedup_similarity_threshold: float,
        retry_count: int,
        retry_backoff_ms: int,
        speech_first_enabled: bool = True,
        initial_chunk_chars: int = 220,
        followup_chunk_chars: int = 650,
        followup_min_chars: int = 60,
        sleep_fn: Callable[[float], None] = time.sleep,
        time_fn: Callable[[], float] = time.perf_counter,
    ) -> None:
        self.extractor = extractor
        self.tts = tts
        self.player = player
        self.min_block_chars = min_block_chars
        self.dedup_enabled = dedup_enabled
        self.deduper = TextDeduper(dedup_similarity_threshold)
        self.retry_count = retry_count
        self.retry_backoff_ms = retry_backoff_ms
        self.speech_first_enabled = speech_first_enabled
        self.initial_chunk_chars = max(initial_chunk_chars, 80)
        self.followup_chunk_chars = max(followup_chunk_chars, self.initial_chunk_chars)
        self.followup_min_chars = max(followup_min_chars, 20)
        self.sleep_fn = sleep_fn
        self.time_fn = time_fn
        self.logger = logging.getLogger("snap_narrate")

    def process_capture(self, image_bytes: bytes, game_profile: str = "default") -> PipelineResult:
        if self.speech_first_enabled:
            speech_first_result = self._process_capture_speech_first(image_bytes=image_bytes, game_profile=game_profile)
            if speech_first_result is not None:
                return speech_first_result
        return self._process_capture_full(image_bytes=image_bytes, game_profile=game_profile)

    def _process_capture_full(self, image_bytes: bytes, game_profile: str = "default") -> PipelineResult:
        start = self.time_fn()

        extract_start = self.time_fn()
        extract = self.extractor.extract_narrative_text(image_bytes=image_bytes, game_profile=game_profile)
        extract_end = self.time_fn()
        extract_ms = int(round((extract_end - extract_start) * 1000))
        if extract.dropped_reason and not extract.text:
            return self._build_result(
                status="skip",
                message=f"Extractor dropped: {extract.dropped_reason}",
                chars=0,
                start=start,
                extract_ms=extract_ms,
            )

        text = normalize_text(extract.text)
        if not text:
            return self._build_result(
                status="skip",
                message="No narrative text extracted",
                chars=0,
                start=start,
                extract_ms=extract_ms,
            )

        if len(text) < self.min_block_chars:
            return self._build_result(
                status="skip",
                message="Text below min_block_chars",
                chars=len(text),
                start=start,
                extract_ms=extract_ms,
            )

        if self.dedup_enabled and self.deduper.seen_recently(text):
            return self._build_result(
                status="skip",
                message="Duplicate text",
                chars=len(text),
                start=start,
                extract_ms=extract_ms,
            )

        tts_start = self.time_fn()
        audio_bytes = self._synthesize_with_retry(text)
        tts_end = self.time_fn()
        tts_ms = int(round((tts_end - tts_start) * 1000))
        if audio_bytes is None:
            return self._build_result(
                status="skip",
                message="TTS failed after retries",
                chars=len(text),
                start=start,
                extract_ms=extract_ms,
                tts_ms=tts_ms,
            )

        playback_start = self.time_fn()
        self.player.play(audio_bytes)
        playback_end = self.time_fn()
        playback_ms = int(round((playback_end - playback_start) * 1000))
        self.logger.info("event=playback_success chars=%s", len(text))
        return self._build_result(
            status="played",
            message="Narration played",
            chars=len(text),
            start=start,
            extract_ms=extract_ms,
            tts_ms=tts_ms,
            playback_ms=playback_ms,
            end=playback_end,
        )

    def _process_capture_speech_first(self, image_bytes: bytes, game_profile: str) -> PipelineResult | None:
        initial_extract_fn = getattr(self.extractor, "extract_initial_narrative_text", None)
        if not callable(initial_extract_fn):
            return None

        start = self.time_fn()
        extract_start = self.time_fn()
        extract = initial_extract_fn(image_bytes=image_bytes, game_profile=game_profile)
        extract_end = self.time_fn()
        extract_ms = int(round((extract_end - extract_start) * 1000))

        initial_text = normalize_text(extract.text)
        initial_chunk_chars = self._adaptive_initial_chunk_chars(initial_text, extract)
        initial_chunk = self._initial_speech_chunk(initial_text, initial_chunk_chars)
        if not initial_chunk or len(initial_chunk) < min(self.min_block_chars, 80):
            return None
        self.logger.info(
            "event=speech_first_chunk_policy source_chars=%s chunk_chars=%s more_text_likely=%s",
            len(initial_text),
            initial_chunk_chars,
            extract.more_text_likely,
        )

        if self.dedup_enabled and self.deduper.seen_recently(initial_chunk):
            return self._build_result(
                status="skip",
                message="Duplicate text",
                chars=len(initial_chunk),
                start=start,
                extract_ms=extract_ms,
            )

        tts_start = self.time_fn()
        audio_bytes = self._synthesize_with_retry(initial_chunk, speech_fast=True)
        tts_end = self.time_fn()
        tts_ms = int(round((tts_end - tts_start) * 1000))
        if audio_bytes is None:
            return self._build_result(
                status="skip",
                message="TTS failed after retries",
                chars=len(initial_chunk),
                start=start,
                extract_ms=extract_ms,
                tts_ms=tts_ms,
            )

        playback_start = self.time_fn()
        self.player.play(audio_bytes)
        playback_end = self.time_fn()
        playback_ms = int(round((playback_end - playback_start) * 1000))
        self.logger.info("event=playback_success chars=%s mode=speech_first_initial", len(initial_chunk))
        threading.Thread(
            target=self._continue_speech_first,
            args=(image_bytes, extract, initial_chunk, game_profile),
            daemon=True,
        ).start()
        return self._build_result(
            status="played",
            message="Narration played",
            chars=len(initial_chunk),
            start=start,
            extract_ms=extract_ms,
            tts_ms=tts_ms,
            playback_ms=playback_ms,
            end=playback_end,
        )

    def _build_result(
        self,
        status: str,
        message: str,
        chars: int,
        start: float,
        extract_ms: int,
        tts_ms: int = 0,
        playback_ms: int = 0,
        end: float | None = None,
    ) -> PipelineResult:
        stop = end if end is not None else self.time_fn()
        timings = PipelineTimings(
            extract_ms=extract_ms,
            tts_ms=tts_ms,
            playback_ms=playback_ms,
            total_ms=int(round((stop - start) * 1000)),
        )
        self.logger.info(
            "event=pipeline_timing status=%s extract_ms=%s tts_ms=%s playback_ms=%s total_ms=%s chars=%s",
            status,
            timings.extract_ms,
            timings.tts_ms,
            timings.playback_ms,
            timings.total_ms,
            chars,
        )
        return PipelineResult(status=status, message=message, chars=chars, timings=timings)

    def process_self_test(self, image_bytes: bytes, game_profile: str = "self-test") -> PipelineResult:
        temp_pipeline = NarrationPipeline(
            extractor=self.extractor,
            tts=self.tts,
            player=self.player,
            min_block_chars=self.min_block_chars,
            dedup_enabled=False,
            dedup_similarity_threshold=1.0,
            retry_count=self.retry_count,
            retry_backoff_ms=self.retry_backoff_ms,
            speech_first_enabled=self.speech_first_enabled,
            initial_chunk_chars=self.initial_chunk_chars,
            followup_chunk_chars=self.followup_chunk_chars,
            followup_min_chars=self.followup_min_chars,
            sleep_fn=self.sleep_fn,
            time_fn=self.time_fn,
        )
        return temp_pipeline.process_capture(image_bytes=image_bytes, game_profile=game_profile)

    def _continue_speech_first(
        self,
        image_bytes: bytes,
        initial_extract: ExtractResult,
        initial_chunk: str,
        game_profile: str,
    ) -> None:
        self.logger.info(
            "event=speech_first_continuation_started initial_chars=%s more_text_likely=%s",
            len(initial_chunk),
            initial_extract.more_text_likely,
        )
        try:
            if not self._should_continue_after_initial(initial_extract, initial_chunk):
                reason = (
                    "extract_signaled_complete"
                    if initial_extract.more_text_likely is False
                    else "initial_chunk_complete"
                )
                self.logger.info("event=speech_first_continuation_skipped reason=%s", reason)
                return
            extract = self.extractor.extract_narrative_text(image_bytes=image_bytes, game_profile=game_profile)
            full_text = normalize_text(extract.text)
            remaining = self._remaining_text(full_text, initial_chunk)
            if not remaining or len(remaining) < self.followup_min_chars:
                self.logger.info("event=speech_first_continuation_skipped reason=no_remaining_text")
                return

            queue_fn = getattr(self.player, "queue", None)
            chunk_count = 0
            for chunk in self._followup_chunks(remaining):
                audio_bytes = self._synthesize_with_retry(chunk)
                if audio_bytes is None:
                    self.logger.warning("event=speech_first_continuation_failed reason=tts_retry_exhausted")
                    return
                if callable(queue_fn):
                    queue_fn(audio_bytes)
                else:
                    self.player.play(audio_bytes)
                chunk_count += 1

            self.logger.info(
                "event=speech_first_continuation_completed chars=%s chunks=%s",
                len(remaining),
                chunk_count,
            )
        except Exception as exc:  # noqa: BLE001
            self.logger.warning("event=speech_first_continuation_failed error=%s", exc)

    def _initial_speech_chunk(self, text: str, chunk_chars: int | None = None) -> str:
        return self._chunk_text(text, chunk_chars or self.initial_chunk_chars)

    def _adaptive_initial_chunk_chars(self, text: str, extract: ExtractResult) -> int:
        normalized = normalize_text(text)
        if not normalized:
            return self.initial_chunk_chars

        chunk_chars = self.initial_chunk_chars
        paragraphs = [part.strip() for part in normalized.split("\n") if part.strip()]
        first_paragraph_len = len(paragraphs[0]) if paragraphs else 0
        total_chars = len(normalized)

        if extract.more_text_likely is False and total_chars <= max(self.initial_chunk_chars + 80, 320):
            return max(chunk_chars, total_chars)

        if extract.more_text_likely is True:
            chunk_chars = min(chunk_chars, 190)

        if total_chars >= 520 or first_paragraph_len >= 420:
            chunk_chars = min(chunk_chars, 140)
        elif extract.more_text_likely is True and (total_chars >= 360 or first_paragraph_len >= 280):
            chunk_chars = min(chunk_chars, 150)
        elif total_chars >= 360 or first_paragraph_len >= 280:
            chunk_chars = min(chunk_chars, 170)

        return max(110, chunk_chars)

    def _chunk_text(self, text: str, chunk_chars: int) -> str:
        normalized = normalize_text(text)
        if not normalized:
            return ""

        paragraphs = [part.strip() for part in normalized.split("\n") if part.strip()]
        if not paragraphs:
            return ""

        first = paragraphs[0]
        if len(first) <= chunk_chars:
            return first

        sentences = [segment.strip() for segment in re.split(r"(?<=[.!?])\s+", first) if segment.strip()]
        out: list[str] = []
        for sentence in sentences:
            candidate = " ".join(out + [sentence]).strip()
            if out and len(candidate) > chunk_chars:
                break
            out.append(sentence)
            if len(candidate) >= chunk_chars:
                break

        if out:
            return " ".join(out).strip()

        truncated = first[:chunk_chars].rsplit(" ", 1)[0].strip()
        return truncated or first[:chunk_chars].strip()

    def _should_continue_after_initial(self, initial_extract: ExtractResult, initial_chunk: str) -> bool:
        if initial_extract.more_text_likely is not None:
            return initial_extract.more_text_likely
        normalized = normalize_text(initial_chunk)
        if not normalized:
            return False
        if len(normalized) >= max(self.initial_chunk_chars - 24, 80):
            return True
        if not normalized.endswith((".", "!", "?", "\"", "'")):
            return True
        return False

    def _remaining_text(self, full_text: str, spoken_text: str) -> str:
        full = normalize_text(full_text)
        spoken = normalize_text(spoken_text)
        if not full or not spoken:
            return full
        if full.lower().startswith(spoken.lower()):
            return full[len(spoken) :].strip()
        spoken_idx = full.lower().find(spoken.lower())
        if 0 <= spoken_idx <= 24:
            return full[spoken_idx + len(spoken) :].strip()

        max_overlap = min(len(full), len(spoken), 500)
        overlap = 0
        for size in range(max_overlap, 20, -1):
            if spoken[-size:].lower() == full[:size].lower():
                overlap = size
                break
        if overlap:
            return full[overlap:].strip()

        fuzzy_remaining = self._fuzzy_remaining_text(full, spoken)
        if fuzzy_remaining is not None:
            return fuzzy_remaining

        self.logger.info(
            "event=speech_first_alignment_failed spoken_chars=%s full_chars=%s",
            len(spoken),
            len(full),
        )
        return ""

    def _fuzzy_remaining_text(self, full_text: str, spoken_text: str) -> str | None:
        spoken = spoken_text.strip()
        full = full_text.strip()
        if not spoken or not full:
            return None

        min_prefix = max(40, int(len(spoken) * 0.55))
        search_limit = min(len(full), max(len(spoken) + 220, int(len(spoken) * 1.5)))
        candidate_endings: set[int] = {min(len(full), len(spoken)), search_limit}
        prefix_window = full[:search_limit]

        for match in re.finditer(r"(?<=[.!?])(?:\s+|$)", prefix_window):
            candidate_endings.add(match.start())

        for idx in range(min_prefix, search_limit + 1, 24):
            candidate_endings.add(idx)
            boundary = prefix_window.rfind(" ", 0, idx + 1)
            if boundary > 0:
                candidate_endings.add(boundary)

        best_end = -1
        best_score = 0.0
        spoken_lower = spoken.lower()
        for end in sorted(candidate_endings):
            if end < min_prefix or end > len(full):
                continue
            prefix = full[:end].strip()
            if not prefix:
                continue
            ratio = SequenceMatcher(None, spoken_lower, prefix.lower()).ratio()
            closeness_penalty = abs(len(prefix) - len(spoken)) / max(len(spoken), 1)
            score = ratio - (closeness_penalty * 0.08)
            if score > best_score:
                best_score = score
                best_end = end

        if best_end < 0:
            return None

        if best_score < 0.72:
            return None

        remaining = full[best_end:].strip()
        if remaining.startswith((",", ";", ":", ")", "]")):
            remaining = remaining[1:].lstrip()
        return remaining

    def _followup_chunks(self, text: str) -> list[str]:
        paragraphs = [part.strip() for part in text.split("\n") if part.strip()]
        chunks: list[str] = []
        for paragraph in paragraphs:
            remaining = paragraph.strip()
            while remaining:
                if len(remaining) <= self.followup_chunk_chars:
                    if len(remaining) >= self.followup_min_chars:
                        chunks.append(remaining)
                    break
                head = self._chunk_text(remaining, self.followup_chunk_chars)
                if not head or head == remaining:
                    if len(remaining) >= self.followup_min_chars:
                        chunks.append(remaining)
                    break
                if len(head) >= self.followup_min_chars:
                    chunks.append(head)
                remaining = self._remaining_text(remaining, head)
        return chunks

    def _synthesize_with_retry(self, text: str, speech_fast: bool = False) -> bytes | None:
        for attempt in range(self.retry_count + 1):
            try:
                if speech_fast:
                    fast_fn = getattr(self.tts, "synthesize_speech_fast", None)
                    if callable(fast_fn):
                        return fast_fn(text)
                return self.tts.synthesize(text)
            except Exception as exc:  # noqa: BLE001
                self.logger.warning("event=tts_failure attempt=%s error=%s", attempt, exc)
                if attempt >= self.retry_count:
                    return None
                backoff_sec = (self.retry_backoff_ms / 1000.0) * (2**attempt)
                self.sleep_fn(backoff_sec)
        return None

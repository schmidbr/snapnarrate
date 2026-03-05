from __future__ import annotations

import logging
import time
from typing import Callable, Protocol

from snap_narrate.models import ExtractResult, PipelineResult
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
        sleep_fn: Callable[[float], None] = time.sleep,
    ) -> None:
        self.extractor = extractor
        self.tts = tts
        self.player = player
        self.min_block_chars = min_block_chars
        self.dedup_enabled = dedup_enabled
        self.deduper = TextDeduper(dedup_similarity_threshold)
        self.retry_count = retry_count
        self.retry_backoff_ms = retry_backoff_ms
        self.sleep_fn = sleep_fn
        self.logger = logging.getLogger("snap_narrate")

    def process_capture(self, image_bytes: bytes, game_profile: str = "default") -> PipelineResult:
        extract = self.extractor.extract_narrative_text(image_bytes=image_bytes, game_profile=game_profile)
        if extract.dropped_reason and not extract.text:
            return PipelineResult(status="skip", message=f"Extractor dropped: {extract.dropped_reason}")

        text = normalize_text(extract.text)
        if not text:
            return PipelineResult(status="skip", message="No narrative text extracted")

        if len(text) < self.min_block_chars:
            return PipelineResult(status="skip", message="Text below min_block_chars", chars=len(text))

        if self.dedup_enabled and self.deduper.seen_recently(text):
            return PipelineResult(status="skip", message="Duplicate text", chars=len(text))

        audio_bytes = self._synthesize_with_retry(text)
        if audio_bytes is None:
            return PipelineResult(status="skip", message="TTS failed after retries", chars=len(text))

        self.player.play(audio_bytes)
        self.logger.info("event=playback_success chars=%s", len(text))
        return PipelineResult(status="played", message="Narration played", chars=len(text))

    def _synthesize_with_retry(self, text: str) -> bytes | None:
        for attempt in range(self.retry_count + 1):
            try:
                return self.tts.synthesize(text)
            except Exception as exc:  # noqa: BLE001
                self.logger.warning("event=tts_failure attempt=%s error=%s", attempt, exc)
                if attempt >= self.retry_count:
                    return None
                backoff_sec = (self.retry_backoff_ms / 1000.0) * (2**attempt)
                self.sleep_fn(backoff_sec)
        return None


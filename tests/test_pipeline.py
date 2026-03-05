from __future__ import annotations

from dataclasses import dataclass

from snap_narrate.models import ExtractResult
from snap_narrate.pipeline import NarrationPipeline


class FakeExtractor:
    def __init__(self, result: ExtractResult) -> None:
        self.result = result

    def extract_narrative_text(self, image_bytes: bytes, game_profile: str = "default") -> ExtractResult:
        return self.result


class FlakyTTS:
    def __init__(self, fail_times: int) -> None:
        self.fail_times = fail_times
        self.calls = 0

    def synthesize(self, text: str) -> bytes:
        self.calls += 1
        if self.calls <= self.fail_times:
            raise RuntimeError("transient")
        return b"audio"


@dataclass
class FakePlayer:
    played: int = 0

    def play(self, audio_bytes: bytes) -> None:
        self.played += 1


def test_pipeline_happy_path() -> None:
    pipeline = NarrationPipeline(
        extractor=FakeExtractor(ExtractResult(text="This is a long narrative block " * 10, confidence=0.9)),
        tts=FlakyTTS(fail_times=0),
        player=FakePlayer(),
        min_block_chars=50,
        dedup_enabled=True,
        dedup_similarity_threshold=0.95,
        retry_count=2,
        retry_backoff_ms=1,
        sleep_fn=lambda _: None,
    )

    result = pipeline.process_capture(b"img")
    assert result.status == "played"


def test_pipeline_retry_then_success() -> None:
    tts = FlakyTTS(fail_times=1)
    player = FakePlayer()
    pipeline = NarrationPipeline(
        extractor=FakeExtractor(ExtractResult(text="Story text " * 20, confidence=0.7)),
        tts=tts,
        player=player,
        min_block_chars=40,
        dedup_enabled=False,
        dedup_similarity_threshold=0.95,
        retry_count=2,
        retry_backoff_ms=1,
        sleep_fn=lambda _: None,
    )

    result = pipeline.process_capture(b"img")
    assert result.status == "played"
    assert tts.calls == 2
    assert player.played == 1


def test_pipeline_retry_then_skip() -> None:
    tts = FlakyTTS(fail_times=3)
    player = FakePlayer()
    pipeline = NarrationPipeline(
        extractor=FakeExtractor(ExtractResult(text="Story text " * 20, confidence=0.7)),
        tts=tts,
        player=player,
        min_block_chars=40,
        dedup_enabled=False,
        dedup_similarity_threshold=0.95,
        retry_count=2,
        retry_backoff_ms=1,
        sleep_fn=lambda _: None,
    )

    result = pipeline.process_capture(b"img")
    assert result.status == "skip"
    assert "TTS failed" in result.message
    assert player.played == 0


def test_pipeline_skip_when_no_text() -> None:
    pipeline = NarrationPipeline(
        extractor=FakeExtractor(ExtractResult(text="", confidence=0.4, dropped_reason="no_narrative_text")),
        tts=FlakyTTS(fail_times=0),
        player=FakePlayer(),
        min_block_chars=40,
        dedup_enabled=True,
        dedup_similarity_threshold=0.95,
        retry_count=2,
        retry_backoff_ms=1,
        sleep_fn=lambda _: None,
    )

    result = pipeline.process_capture(b"img")
    assert result.status == "skip"


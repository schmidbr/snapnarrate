from __future__ import annotations

from dataclasses import dataclass

from snap_narrate.models import ExtractResult
from snap_narrate.pipeline import NarrationPipeline


class FakeExtractor:
    def __init__(self, result: ExtractResult, initial_result: ExtractResult | None = None) -> None:
        self.result = result
        self.initial_result = initial_result or result

    def extract_narrative_text(self, image_bytes: bytes, game_profile: str = "default") -> ExtractResult:
        return self.result

    def extract_initial_narrative_text(self, image_bytes: bytes, game_profile: str = "default") -> ExtractResult:
        return self.initial_result


class FlakyTTS:
    def __init__(self, fail_times: int) -> None:
        self.fail_times = fail_times
        self.calls = 0

    def synthesize(self, text: str) -> bytes:
        self.calls += 1
        if self.calls <= self.fail_times:
            raise RuntimeError("transient")
        return b"audio"

    def synthesize_speech_fast(self, text: str) -> bytes:
        return self.synthesize(text)


@dataclass
class FakePlayer:
    played: int = 0
    queued: int = 0

    def play(self, audio_bytes: bytes) -> None:
        self.played += 1

    def queue(self, audio_bytes: bytes) -> None:
        self.queued += 1


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
        speech_first_enabled=False,
        sleep_fn=lambda _: None,
    )

    result = pipeline.process_capture(b"img")
    assert result.status == "played"
    assert result.timings is not None
    assert result.timings.extract_ms >= 0
    assert result.timings.tts_ms >= 0
    assert result.timings.playback_ms >= 0
    assert result.timings.total_ms >= 0


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
        speech_first_enabled=False,
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
        speech_first_enabled=False,
        sleep_fn=lambda _: None,
    )

    result = pipeline.process_capture(b"img")
    assert result.status == "skip"
    assert "TTS failed" in result.message
    assert player.played == 0
    assert result.timings is not None
    assert result.timings.tts_ms >= 0


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
        speech_first_enabled=False,
        sleep_fn=lambda _: None,
    )

    result = pipeline.process_capture(b"img")
    assert result.status == "skip"
    assert result.timings is not None


def test_pipeline_reports_deterministic_timings() -> None:
    times = iter([0.0, 0.01, 0.04, 0.05, 0.09, 0.10, 0.13])
    pipeline = NarrationPipeline(
        extractor=FakeExtractor(ExtractResult(text="Story text " * 20, confidence=0.9)),
        tts=FlakyTTS(fail_times=0),
        player=FakePlayer(),
        min_block_chars=40,
        dedup_enabled=False,
        dedup_similarity_threshold=0.95,
        retry_count=0,
        retry_backoff_ms=1,
        speech_first_enabled=False,
        sleep_fn=lambda _: None,
        time_fn=lambda: next(times),
    )

    result = pipeline.process_capture(b"img")

    assert result.timings is not None
    assert result.timings.extract_ms == 30
    assert result.timings.tts_ms == 40
    assert result.timings.playback_ms == 30
    assert result.timings.total_ms == 130


def test_pipeline_self_test_bypasses_dedup() -> None:
    player = FakePlayer()
    pipeline = NarrationPipeline(
        extractor=FakeExtractor(ExtractResult(text="Story text " * 20, confidence=0.9)),
        tts=FlakyTTS(fail_times=0),
        player=player,
        min_block_chars=40,
        dedup_enabled=True,
        dedup_similarity_threshold=0.95,
        retry_count=0,
        retry_backoff_ms=1,
        speech_first_enabled=False,
        sleep_fn=lambda _: None,
    )

    first = pipeline.process_capture(b"img")
    second = pipeline.process_self_test(b"img")

    assert first.status == "played"
    assert second.status == "played"
    assert player.played == 2


def test_pipeline_speech_first_plays_initial_chunk_and_queues_tail(monkeypatch) -> None:
    extractor = FakeExtractor(
        result=ExtractResult(
            text="First paragraph continues without a clean ending and then leads into more text.\n\nSecond paragraph follows with more story.",
            confidence=0.9,
        ),
        initial_result=ExtractResult(
            text="First paragraph continues without a clean ending and then leads into more text",
            confidence=0.95,
        ),
    )
    tts = FlakyTTS(fail_times=0)
    player = FakePlayer()
    pipeline = NarrationPipeline(
        extractor=extractor,
        tts=tts,
        player=player,
        min_block_chars=10,
        dedup_enabled=False,
        dedup_similarity_threshold=0.95,
        retry_count=0,
        retry_backoff_ms=1,
        speech_first_enabled=True,
        initial_chunk_chars=80,
        followup_chunk_chars=120,
        followup_min_chars=20,
        sleep_fn=lambda _: None,
    )

    class ImmediateThread:
        def __init__(self, target, args=(), kwargs=None, daemon=None):  # noqa: ANN001,ARG002
            self._target = target
            self._args = args
            self._kwargs = kwargs or {}

        def start(self) -> None:
            self._target(*self._args, **self._kwargs)

    monkeypatch.setattr("snap_narrate.pipeline.threading.Thread", ImmediateThread)

    result = pipeline.process_capture(b"img")

    assert result.status == "played"
    assert player.played == 1
    assert player.queued == 1


def test_pipeline_speech_first_skips_full_followup_when_initial_chunk_is_complete(monkeypatch) -> None:
    class GuardExtractor(FakeExtractor):
        def extract_narrative_text(self, image_bytes: bytes, game_profile: str = "default") -> ExtractResult:
            raise AssertionError("full extraction should have been skipped")

    extractor = GuardExtractor(
        result=ExtractResult(text="Unused.", confidence=0.9),
        initial_result=ExtractResult(text="A complete short paragraph.", confidence=0.98),
    )
    pipeline = NarrationPipeline(
        extractor=extractor,
        tts=FlakyTTS(fail_times=0),
        player=FakePlayer(),
        min_block_chars=10,
        dedup_enabled=False,
        dedup_similarity_threshold=0.95,
        retry_count=0,
        retry_backoff_ms=1,
        speech_first_enabled=True,
        initial_chunk_chars=120,
        sleep_fn=lambda _: None,
    )

    class ImmediateThread:
        def __init__(self, target, args=(), kwargs=None, daemon=None):  # noqa: ANN001,ARG002
            self._target = target
            self._args = args
            self._kwargs = kwargs or {}

        def start(self) -> None:
            self._target(*self._args, **self._kwargs)

    monkeypatch.setattr("snap_narrate.pipeline.threading.Thread", ImmediateThread)

    result = pipeline.process_capture(b"img")

    assert result.status == "played"


def test_pipeline_speech_first_skips_full_followup_when_initial_extract_signals_complete(monkeypatch) -> None:
    class GuardExtractor(FakeExtractor):
        def extract_narrative_text(self, image_bytes: bytes, game_profile: str = "default") -> ExtractResult:
            raise AssertionError("full extraction should have been skipped")

    extractor = GuardExtractor(
        result=ExtractResult(text="Unused.", confidence=0.9),
        initial_result=ExtractResult(
            text=(
                "This paragraph is intentionally long enough to trigger the old continuation heuristic even though the "
                "extractor already knows the first result is the whole thing"
            ),
            confidence=0.98,
            more_text_likely=False,
        ),
    )
    pipeline = NarrationPipeline(
        extractor=extractor,
        tts=FlakyTTS(fail_times=0),
        player=FakePlayer(),
        min_block_chars=10,
        dedup_enabled=False,
        dedup_similarity_threshold=0.95,
        retry_count=0,
        retry_backoff_ms=1,
        speech_first_enabled=True,
        initial_chunk_chars=120,
        sleep_fn=lambda _: None,
    )

    class ImmediateThread:
        def __init__(self, target, args=(), kwargs=None, daemon=None):  # noqa: ANN001,ARG002
            self._target = target
            self._args = args
            self._kwargs = kwargs or {}

        def start(self) -> None:
            self._target(*self._args, **self._kwargs)

    monkeypatch.setattr("snap_narrate.pipeline.threading.Thread", ImmediateThread)

    result = pipeline.process_capture(b"img")

    assert result.status == "played"


def test_pipeline_speech_first_continues_when_initial_extract_signals_more_text(monkeypatch) -> None:
    class CountingExtractor(FakeExtractor):
        def __init__(self, result: ExtractResult, initial_result: ExtractResult) -> None:
            super().__init__(result=result, initial_result=initial_result)
            self.full_extract_calls = 0

        def extract_narrative_text(self, image_bytes: bytes, game_profile: str = "default") -> ExtractResult:
            self.full_extract_calls += 1
            return self.result

    extractor = CountingExtractor(
        result=ExtractResult(
            text="Short complete paragraph.\n\nSecond paragraph follows with more story to narrate next.",
            confidence=0.9,
        ),
        initial_result=ExtractResult(
            text="Short complete paragraph.",
            confidence=0.98,
            more_text_likely=True,
        ),
    )
    player = FakePlayer()
    pipeline = NarrationPipeline(
        extractor=extractor,
        tts=FlakyTTS(fail_times=0),
        player=player,
        min_block_chars=10,
        dedup_enabled=False,
        dedup_similarity_threshold=0.95,
        retry_count=0,
        retry_backoff_ms=1,
        speech_first_enabled=True,
        initial_chunk_chars=120,
        followup_chunk_chars=120,
        followup_min_chars=20,
        sleep_fn=lambda _: None,
    )

    class ImmediateThread:
        def __init__(self, target, args=(), kwargs=None, daemon=None):  # noqa: ANN001,ARG002
            self._target = target
            self._args = args
            self._kwargs = kwargs or {}

        def start(self) -> None:
            self._target(*self._args, **self._kwargs)

    monkeypatch.setattr("snap_narrate.pipeline.threading.Thread", ImmediateThread)

    result = pipeline.process_capture(b"img")

    assert result.status == "played"
    assert extractor.full_extract_calls == 1
    assert player.queued == 1


def test_adaptive_initial_chunk_chars_keeps_short_complete_block_intact() -> None:
    pipeline = NarrationPipeline(
        extractor=FakeExtractor(ExtractResult(text="Story text " * 20, confidence=0.9)),
        tts=FlakyTTS(fail_times=0),
        player=FakePlayer(),
        min_block_chars=20,
        dedup_enabled=False,
        dedup_similarity_threshold=0.95,
        retry_count=0,
        retry_backoff_ms=1,
        speech_first_enabled=True,
        initial_chunk_chars=180,
        sleep_fn=lambda _: None,
    )

    text = "A short complete paragraph that should be spoken as one block without being aggressively shortened."
    extract = ExtractResult(text=text, confidence=0.98, more_text_likely=False)

    chunk_chars = pipeline._adaptive_initial_chunk_chars(text, extract)
    initial_chunk = pipeline._initial_speech_chunk(text, chunk_chars)

    assert chunk_chars >= len(text)
    assert initial_chunk == text


def test_adaptive_initial_chunk_chars_reduces_long_continuing_block() -> None:
    pipeline = NarrationPipeline(
        extractor=FakeExtractor(ExtractResult(text="Story text " * 20, confidence=0.9)),
        tts=FlakyTTS(fail_times=0),
        player=FakePlayer(),
        min_block_chars=20,
        dedup_enabled=False,
        dedup_similarity_threshold=0.95,
        retry_count=0,
        retry_backoff_ms=1,
        speech_first_enabled=True,
        initial_chunk_chars=220,
        sleep_fn=lambda _: None,
    )

    text = (
        "This is a long first paragraph designed to keep running for quite a while before it reaches a natural stopping point. "
        "It keeps describing the scene in enough detail that the adaptive policy should clamp the initial spoken chunk to start audio sooner. "
        "Another sentence extends the opening even more so the total block is clearly large enough to trigger the tighter cap."
    )
    extract = ExtractResult(text=text, confidence=0.95, more_text_likely=True)

    chunk_chars = pipeline._adaptive_initial_chunk_chars(text, extract)
    initial_chunk = pipeline._initial_speech_chunk(text, chunk_chars)

    assert chunk_chars == 150
    assert len(initial_chunk) <= 150


def test_remaining_text_uses_fuzzy_prefix_alignment_for_rephrased_opening() -> None:
    pipeline = NarrationPipeline(
        extractor=FakeExtractor(ExtractResult(text="Story text " * 20, confidence=0.9)),
        tts=FlakyTTS(fail_times=0),
        player=FakePlayer(),
        min_block_chars=20,
        dedup_enabled=False,
        dedup_similarity_threshold=0.95,
        retry_count=0,
        retry_backoff_ms=1,
        speech_first_enabled=True,
        sleep_fn=lambda _: None,
    )

    spoken = "He glanced around the ruined chapel. The candles were all cold and dark."
    full = (
        "He glanced around the ruined chapel, noting that the candles were all cold and dark. "
        "A draft moved through the broken door."
    )

    remaining = pipeline._remaining_text(full, spoken)

    assert remaining == "A draft moved through the broken door."


def test_pipeline_speech_first_skips_followup_when_full_extract_only_repeats_opening(monkeypatch) -> None:
    class CountingExtractor(FakeExtractor):
        def __init__(self, result: ExtractResult, initial_result: ExtractResult) -> None:
            super().__init__(result=result, initial_result=initial_result)
            self.full_extract_calls = 0

        def extract_narrative_text(self, image_bytes: bytes, game_profile: str = "default") -> ExtractResult:
            self.full_extract_calls += 1
            return self.result

    extractor = CountingExtractor(
        result=ExtractResult(
            text="He glanced around the ruined chapel, noting that the candles were all cold and dark.",
            confidence=0.95,
        ),
        initial_result=ExtractResult(
            text="He glanced around the ruined chapel. The candles were all cold and dark.",
            confidence=0.98,
            more_text_likely=True,
        ),
    )
    player = FakePlayer()
    pipeline = NarrationPipeline(
        extractor=extractor,
        tts=FlakyTTS(fail_times=0),
        player=player,
        min_block_chars=10,
        dedup_enabled=False,
        dedup_similarity_threshold=0.95,
        retry_count=0,
        retry_backoff_ms=1,
        speech_first_enabled=True,
        initial_chunk_chars=140,
        followup_chunk_chars=140,
        followup_min_chars=20,
        sleep_fn=lambda _: None,
    )

    class ImmediateThread:
        def __init__(self, target, args=(), kwargs=None, daemon=None):  # noqa: ANN001,ARG002
            self._target = target
            self._args = args
            self._kwargs = kwargs or {}

        def start(self) -> None:
            self._target(*self._args, **self._kwargs)

    monkeypatch.setattr("snap_narrate.pipeline.threading.Thread", ImmediateThread)

    result = pipeline.process_capture(b"img")

    assert result.status == "played"
    assert extractor.full_extract_calls == 1
    assert player.queued == 0


def test_followup_chunks_skip_tiny_tail() -> None:
    pipeline = NarrationPipeline(
        extractor=FakeExtractor(ExtractResult(text="Story text " * 20, confidence=0.9)),
        tts=FlakyTTS(fail_times=0),
        player=FakePlayer(),
        min_block_chars=20,
        dedup_enabled=False,
        dedup_similarity_threshold=0.95,
        retry_count=0,
        retry_backoff_ms=1,
        speech_first_enabled=True,
        initial_chunk_chars=80,
        followup_chunk_chars=100,
        followup_min_chars=30,
        sleep_fn=lambda _: None,
    )

    chunks = pipeline._followup_chunks("This is a longer paragraph that should stay. Tiny tail.")

    assert all(len(chunk) >= 30 for chunk in chunks)

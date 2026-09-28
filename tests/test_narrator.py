from __future__ import annotations

from snap_narrate.audio import AudioPlayer
from snap_narrate.narrator import Narrator, NarratorSettings, Session
from snap_narrate.providers.base import ExtractResult

from conftest import FakeSpeech, FakeVision, run_now

LONG = "This is a long narrative block that keeps going. " * 12


def make(vision: FakeVision, speech: FakeSpeech, player: AudioPlayer, spawn=run_now, **settings) -> Narrator:  # noqa: ANN001
    defaults = dict(min_block_chars=40, retry_backoff_ms=1, speech_first_enabled=False)
    defaults.update(settings)
    return Narrator(vision, speech, player, NarratorSettings(**defaults), sleep_fn=lambda _s: None, spawn=spawn)


def test_full_path_speaks_every_chunk(player: AudioPlayer) -> None:
    speech = FakeSpeech()
    narrator = make(FakeVision(ExtractResult(LONG)), speech, player, initial_chunk_chars=120, followup_chunk_chars=200)
    result = narrator.narrate(b"img", Session(1))
    assert result.played
    spoken = " ".join(text for text, _ in speech.calls)
    assert spoken.count("This is a long") == 12
    assert speech.calls[0][1] is False


def test_retry_then_success(player: AudioPlayer) -> None:
    speech = FakeSpeech(fail_times=1)
    result = make(FakeVision(ExtractResult("Story text " * 10)), speech, player).narrate(b"img", Session(1))
    assert result.played


def test_retry_exhausted_fails(player: AudioPlayer) -> None:
    result = make(FakeVision(ExtractResult("Story text " * 10)), FakeSpeech(fail_times=5), player, retry_count=2).narrate(b"img", Session(1))
    assert result.status == "failed"


def test_skips_empty_short_and_duplicate(player: AudioPlayer) -> None:
    assert make(FakeVision(ExtractResult("", dropped_reason="menu")), FakeSpeech(), player).narrate(b"", Session(1)).status == "skipped"
    assert make(FakeVision(ExtractResult("tiny")), FakeSpeech(), player).narrate(b"", Session(1)).status == "skipped"
    narrator = make(FakeVision(ExtractResult(LONG)), FakeSpeech(), player)
    assert narrator.narrate(b"", Session(1)).played
    assert narrator.narrate(b"", Session(2)).message == "Already read this text"
    assert narrator.narrate(b"", Session(3), dedup=False).played


def test_speech_first_uses_fast_model_then_queues_tail(player: AudioPlayer) -> None:
    vision = FakeVision(
        full=ExtractResult("Short complete paragraph.\nSecond paragraph follows with more story to narrate next."),
        first=ExtractResult("Short complete paragraph.", more_text_likely=True),
    )
    speech = FakeSpeech()
    narrator = make(vision, speech, player, min_block_chars=10, speech_first_enabled=True, followup_min_chars=20)
    assert narrator.narrate(b"img", Session(1)).played
    assert speech.calls[0] == ("Short complete paragraph.", True)
    assert speech.calls[1][0].startswith("Second paragraph")
    assert vision.full_calls == 1


def test_speech_first_skips_second_pass_when_model_says_complete(player: AudioPlayer) -> None:
    vision = FakeVision(full=ExtractResult("unused"), first=ExtractResult("A complete paragraph that is the whole thing. " * 3, more_text_likely=False))
    narrator = make(vision, FakeSpeech(), player, min_block_chars=10, speech_first_enabled=True)
    assert narrator.narrate(b"img", Session(1)).played
    assert vision.full_calls == 0


def test_speech_first_falls_back_to_full_when_first_pass_is_empty(player: AudioPlayer) -> None:
    vision = FakeVision(full=ExtractResult(LONG), first=ExtractResult(""))
    assert make(vision, FakeSpeech(), player, speech_first_enabled=True).narrate(b"img", Session(1)).played
    assert vision.full_calls == 1


# ---- regressions: Stop and overlapping captures ----------------------------------------


def test_cancelled_session_stops_background_continuation(player: AudioPlayer) -> None:
    """Stop during the tail must not synthesize or queue anything further."""
    session = Session(1)
    speech = FakeSpeech(before=lambda text: session.cancel() if len(speech.calls) == 1 else None)
    narrator = make(FakeVision(ExtractResult(LONG)), speech, player, initial_chunk_chars=100, followup_chunk_chars=120)
    narrator.narrate(b"img", session)
    # First chunk played, cancel happened while synthesizing chunk 2: nothing after that.
    assert len(speech.calls) == 2


def test_stop_prevents_late_queue(player: AudioPlayer) -> None:
    deferred: list = []
    speech = FakeSpeech()
    narrator = make(FakeVision(ExtractResult(LONG)), speech, player, spawn=deferred.append, initial_chunk_chars=100)
    session = Session(1)
    assert narrator.narrate(b"img", session).played
    session.cancel()
    player.stop()
    deferred[0]()  # the background tail runs after Stop
    assert len(speech.calls) == 1  # nothing synthesized after Stop
    assert player.session == 0 and not player.is_playing


def test_new_capture_drops_previous_tail(player: AudioPlayer) -> None:
    deferred: list = []
    speech = FakeSpeech()
    narrator = make(FakeVision(ExtractResult(LONG)), speech, player, spawn=deferred.append, initial_chunk_chars=100)
    first, second = Session(1), Session(2)
    narrator.narrate(b"a", first)
    first.cancel()  # the engine cancels the old session when a new one starts
    narrator.narrate(b"b", second, dedup=False)
    calls_before = len(speech.calls)
    deferred[0]()  # capture A's tail wakes up late
    assert len(speech.calls) == calls_before
    assert player.session == 2


def test_plan_is_published_then_extended_for_speech_first(player: AudioPlayer) -> None:
    from snap_narrate import events
    from snap_narrate.events import EventBus

    bus = EventBus()
    plans: list[dict] = []
    bus.subscribe(events.NARRATION_PLAN, lambda e: plans.append(e.data))
    vision = FakeVision(
        full=ExtractResult("Short complete paragraph.\nSecond paragraph follows with more story to narrate next."),
        first=ExtractResult("Short complete paragraph.", more_text_likely=True),
    )
    narrator = make(vision, FakeSpeech(), player, min_block_chars=10, speech_first_enabled=True, followup_min_chars=20)
    narrator.bus = bus
    narrator.narrate(b"img", Session(4))
    assert plans[0] == {"session": 4, "chunk_chars": [25], "final": False}
    assert plans[1]["final"] is True and len(plans[1]["chunk_chars"]) == 2


def test_plan_is_final_immediately_on_full_path(player: AudioPlayer) -> None:
    from snap_narrate import events
    from snap_narrate.events import EventBus

    bus = EventBus()
    plans: list[dict] = []
    bus.subscribe(events.NARRATION_PLAN, lambda e: plans.append(e.data))
    narrator = make(FakeVision(ExtractResult(LONG)), FakeSpeech(), player, initial_chunk_chars=120, followup_chunk_chars=200)
    narrator.bus = bus
    narrator.narrate(b"img", Session(1))
    assert len(plans) == 1 and plans[0]["final"] is True and len(plans[0]["chunk_chars"]) > 1

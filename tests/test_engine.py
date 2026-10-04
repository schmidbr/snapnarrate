from __future__ import annotations

import threading

import pytest

from snap_narrate import events
from snap_narrate.config import AppConfig
from snap_narrate.engine import Engine
from snap_narrate.events import EventBus
from snap_narrate.narrator import Narrator, NarratorSettings
from snap_narrate.providers.base import ExtractResult

from conftest import FakeSpeech, FakeVision, RecordingOutput

TEXT = "The lantern flickered as the caravan crossed the dunes under a pale moon. " * 3


class FakeCapturer:
    def __init__(self) -> None:
        self.shots = 0

    def fullscreen(self) -> bytes:
        self.shots += 1
        return b"shot"

    def region(self, bounds) -> bytes:  # noqa: ANN001
        self.shots += 1
        return b"region"

    def encode(self, image) -> bytes:  # noqa: ANN001
        return b"encoded"


def configured() -> AppConfig:
    cfg = AppConfig()
    cfg.openai.api_key = cfg.elevenlabs.api_key = cfg.elevenlabs.voice_id = "x"
    cfg.elevenlabs.output_format = "pcm_16000"
    cfg.playback.speech_first_enabled = False
    cfg.capture.sound_name = "None"
    return cfg


@pytest.fixture
def engine_parts():
    bus = EventBus()
    seen: list[events.Event] = []
    bus.subscribe(events.ALL, seen.append)
    vision = FakeVision(ExtractResult(TEXT))
    speech = FakeSpeech()
    capturer = FakeCapturer()
    from snap_narrate.audio import AudioPlayer

    player = AudioPlayer("pcm_16000", output=RecordingOutput())

    def factory(cfg, player_, bus_):  # noqa: ANN001
        return Narrator(vision, speech, player_, NarratorSettings.from_config(cfg), bus=bus_)

    engine = Engine(
        configured(),
        bus,
        region_picker=lambda: (0, 0, 200, 200),
        player=player,
        capturer=capturer,  # type: ignore[arg-type]
        narrator_factory=factory,
    )
    yield engine, seen, vision, speech, capturer
    engine.close()


def finished(seen: list[events.Event], timeout: float = 2.0) -> events.Event:
    done = threading.Event()
    for _ in range(int(timeout / 0.01)):
        hits = [e for e in seen if e.topic == events.NARRATION_FINISHED]
        if hits:
            return hits[-1]
        done.wait(0.01)
    raise AssertionError("narration did not finish")


def fully_cached(engine: Engine, session: int, timeout: float = 2.0) -> None:
    """Wait until the background tail has voiced the rest of the passage."""
    done = threading.Event()
    for _ in range(int(timeout / 0.01)):
        if session in engine._audio_done:
            return
        done.wait(0.01)
    raise AssertionError("passage audio was never completed")


def test_capture_narrates_and_reports(engine_parts) -> None:  # noqa: ANN001
    engine, seen, vision, _speech, capturer = engine_parts
    engine.capture_fullscreen()
    event = finished(seen)
    assert event.data["status"] == "played"
    assert capturer.shots == 1 and vision.full_calls == 1
    assert any(e.topic == events.CAPTURE for e in seen)


def test_paused_engine_ignores_captures(engine_parts) -> None:  # noqa: ANN001
    engine, seen, _vision, _speech, capturer = engine_parts
    engine.set_paused(True)
    engine.capture()
    assert capturer.shots == 0
    assert any(e.topic == events.NOTICE and "paused" in e.data["message"] for e in seen)


def test_incomplete_setup_is_reported_not_crashed(engine_parts) -> None:  # noqa: ANN001
    engine, seen, _vision, _speech, capturer = engine_parts
    cfg = configured()
    cfg.elevenlabs.api_key = ""
    engine.configure(cfg)
    engine.capture()
    assert capturer.shots == 0
    assert any("Setup incomplete" in e.data.get("message", "") for e in seen if e.topic == events.NOTICE)


def test_region_capture_uses_picker(engine_parts) -> None:  # noqa: ANN001
    engine, seen, _vision, _speech, capturer = engine_parts
    engine.set_capture_mode("region")
    engine.capture()
    assert finished(seen).data["source"] == "hotkey:region"


def test_speak_text_skips_extraction(engine_parts) -> None:  # noqa: ANN001
    engine, _seen, vision, speech, _capturer = engine_parts
    result = engine.speak("Hello from an addon. " * 3).result(timeout=2)
    assert result.played
    assert vision.full_calls == 0 and speech.calls


def test_self_test_bypasses_dedup(engine_parts) -> None:  # noqa: ANN001
    engine, seen, _vision, _speech, _capturer = engine_parts
    engine.capture_fullscreen()
    finished(seen)
    assert engine.self_test(timeout=2).played


def test_stop_cancels_live_session(engine_parts) -> None:  # noqa: ANN001
    engine, seen, _vision, _speech, _capturer = engine_parts
    engine.capture_fullscreen()
    finished(seen)
    session = engine._session
    engine.stop_speaking()
    assert session is not None and session.cancelled
    assert engine.player.session == 0


def test_replay_uses_cached_audio_without_new_speech(engine_parts) -> None:  # noqa: ANN001
    from snap_narrate.history import HistoryEntry

    engine, seen, _vision, speech, _capturer = engine_parts
    engine.capture_fullscreen()
    session = finished(seen).data["session"]
    fully_cached(engine, session)
    calls_before = len(speech.calls)
    entry = HistoryEntry(id="x", time=0, source="hotkey", text=TEXT, run_id=engine.run_id, session=session)
    result = engine.replay(entry).result(timeout=2)
    assert result.played and result.message == "Replaying"
    assert len(speech.calls) == calls_before  # no new ElevenLabs request


def test_replay_of_a_stopped_passage_voices_the_whole_text_again(engine_parts) -> None:  # noqa: ANN001
    from snap_narrate.history import HistoryEntry

    engine, seen, _vision, speech, _capturer = engine_parts
    stopped = threading.Event()

    def stop_during_tail(_text: str) -> None:
        if len(speech.calls) == 1:  # the first chunk is playing; Stop while the next is voiced
            engine.stop_speaking()
            stopped.set()

    speech.before = stop_during_tail
    engine.capture_fullscreen()
    session = finished(seen).data["session"]
    assert stopped.wait(2)
    calls_before = len(speech.calls)
    entry = HistoryEntry(id="x", time=0, source="hotkey", text=TEXT, run_id=engine.run_id, session=session)
    result = engine.replay(entry).result(timeout=2)
    assert result.played and result.message != "Replaying"
    assert len(speech.calls) > calls_before  # voiced again, not the partial cached audio
    assert TEXT.strip().startswith(speech.calls[calls_before][0][:40])


def test_replay_from_an_older_run_voices_the_text_again(engine_parts) -> None:  # noqa: ANN001
    from snap_narrate.history import HistoryEntry

    engine, _seen, _vision, speech, _capturer = engine_parts
    entry = HistoryEntry(id="y", time=0, source="hotkey", text="An old passage from yesterday, read aloud again.", run_id="old-run", session=1)
    assert engine.replay(entry).result(timeout=2).played
    assert speech.calls and speech.calls[0][0].startswith("An old passage")


def test_history_records_a_real_capture_and_replays_it(engine_parts, tmp_path) -> None:  # noqa: ANN001
    from snap_narrate.history import History

    engine, seen, _vision, speech, _capturer = engine_parts
    history = History(tmp_path / "history.json")
    history.run_id = engine.run_id
    history.attach(engine.bus)
    engine.capture_fullscreen()
    fully_cached(engine, finished(seen).data["session"])
    entry = history.latest()
    assert entry is not None and entry.text.startswith("The lantern flickered") and entry.trigger == "Full screen"
    calls = len(speech.calls)
    assert engine.replay(entry).result(timeout=2).played
    assert len(speech.calls) == calls and len(history.entries()) == 1  # free replay, not re-recorded

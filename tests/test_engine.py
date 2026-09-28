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

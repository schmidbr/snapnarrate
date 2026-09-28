from __future__ import annotations

import sys
import types
from pathlib import Path

from snap_narrate.models import PipelineResult, PipelineTimings
from snap_narrate.runtime import SnapNarrateRuntime


class _DummyPipeline:
    def __init__(self) -> None:
        self.self_test_calls: list[tuple[bytes, str]] = []

    def process_self_test(self, image_bytes: bytes, game_profile: str = "self-test") -> PipelineResult:
        self.self_test_calls.append((image_bytes, game_profile))
        return PipelineResult(
            status="played",
            message="Narration played",
            chars=120,
            timings=PipelineTimings(extract_ms=10, tts_ms=20, playback_ms=5, total_ms=35),
        )


class _DummyCapturer:
    def capture_fullscreen_png(self) -> bytes:
        return b"full"

    def capture_region_png(self, bounds) -> bytes:  # noqa: ANN001
        return b"region"


def _runtime(region_selector):
    return SnapNarrateRuntime(
        capturer=_DummyCapturer(),  # type: ignore[arg-type]
        pipeline=_DummyPipeline(),  # type: ignore[arg-type]
        hotkey="ctrl+shift+n",
        region_hotkey="ctrl+shift+r",
        stop_hotkey="ctrl+shift+s",
        capture_mode="fullscreen",
        min_region_px=64,
        log_path=Path("logs/test.log"),
        capture_sound_name="Windows Balloon",
        region_selector=region_selector,
    )


def test_runtime_registers_region_hotkey(monkeypatch) -> None:
    calls = []

    def fake_add_hotkey(combo, cb):  # noqa: ANN001
        calls.append(combo)
        return None

    monkeypatch.setattr("keyboard.add_hotkey", fake_add_hotkey)
    rt = _runtime(lambda: None)
    rt._register_hotkeys()
    assert "ctrl+shift+n" in calls
    assert "ctrl+shift+r" in calls
    assert "ctrl+shift+s" in calls


def test_region_capture_cancelled_does_not_enqueue() -> None:
    rt = _runtime(lambda: None)
    rt._capture_region_once()
    assert rt._pending_capture is None


def test_region_capture_valid_enqueues() -> None:
    rt = _runtime(lambda: (10, 10, 200, 120))
    rt._capture_region_once()
    assert rt._pending_capture == b"region"
    assert rt._work_event.is_set()


def test_fullscreen_hotkey_notifies_before_capture() -> None:
    rt = _runtime(lambda: None)
    notifications: list[str] = []
    sounds: list[str] = []
    rt._notify = notifications.append  # type: ignore[method-assign]
    rt._play_capture_sound = lambda: sounds.append("beep")  # type: ignore[method-assign]

    rt._on_hotkey()

    assert notifications == ["Hotkey pressed: capturing full screen"]
    assert sounds == ["beep"]
    assert rt._pending_capture == b"full"


def test_region_hotkey_notifies_before_region_selection() -> None:
    rt = _runtime(lambda: (10, 10, 200, 120))
    notifications: list[str] = []
    sounds: list[str] = []
    rt._notify = notifications.append  # type: ignore[method-assign]
    rt._play_capture_sound = lambda: sounds.append("beep")  # type: ignore[method-assign]

    rt._on_region_hotkey()

    assert notifications == ["Hotkey pressed: select a region"]
    assert sounds == ["beep"]
    assert rt._pending_capture == b"region"


def test_paused_hotkeys_notify_and_do_not_enqueue() -> None:
    rt = _runtime(lambda: (10, 10, 200, 120))
    notifications: list[str] = []
    rt._notify = notifications.append  # type: ignore[method-assign]
    rt.state.paused = True

    rt._on_hotkey()
    rt._on_region_hotkey()

    assert notifications == ["Capture ignored: paused", "Capture ignored: paused"]
    assert rt._pending_capture is None


def test_region_capture_cancelled_does_not_play_sound() -> None:
    rt = _runtime(lambda: None)
    sounds: list[str] = []
    rt._play_capture_sound = lambda: sounds.append("beep")  # type: ignore[method-assign]

    rt._capture_region_once()

    assert sounds == []


def test_runtime_self_test_notifies_success(monkeypatch) -> None:
    rt = _runtime(lambda: None)
    notifications: list[str] = []
    rt._notify = notifications.append  # type: ignore[method-assign]
    monkeypatch.setattr("snap_narrate.runtime.create_self_test_image_bytes", lambda **kwargs: b"fixture")

    rt._run_self_test()

    assert notifications == ["Running self-test", "Self-test passed in 35 ms"]
    assert rt.pipeline.self_test_calls == [(b"fixture", "self-test")]


def test_runtime_self_test_rejects_parallel_runs() -> None:
    rt = _runtime(lambda: None)
    notifications: list[str] = []
    rt._notify = notifications.append  # type: ignore[method-assign]
    rt._self_test_running = True

    rt._tray_run_self_test(None, None)  # type: ignore[arg-type]

    assert notifications == ["Self-test already running"]


def test_play_capture_sound_prefers_windows_balloon_sound(monkeypatch, tmp_path) -> None:
    rt = _runtime(lambda: None)
    calls: list[tuple[str, int]] = []
    fake_winsound = types.SimpleNamespace(
        PlaySound=lambda sound, flags: calls.append((sound, flags)),
        SND_FILENAME=1,
        SND_ASYNC=2,
        SND_NODEFAULT=4,
        SND_ALIAS=8,
    )
    monkeypatch.setitem(sys.modules, "winsound", fake_winsound)
    monkeypatch.setenv("WINDIR", str(tmp_path))

    media_dir = tmp_path / "Media"
    media_dir.mkdir()
    expected = media_dir / "Windows Balloon.wav"
    expected.write_bytes(b"wav")

    rt._play_capture_sound()

    assert calls == [(str(expected), 7)]


def test_play_capture_sound_uses_selected_windows_sound(monkeypatch, tmp_path) -> None:
    rt = _runtime(lambda: None)
    rt.capture_sound_name = "Windows Ding"
    calls: list[tuple[str, int]] = []
    fake_winsound = types.SimpleNamespace(
        PlaySound=lambda sound, flags: calls.append((sound, flags)),
        SND_FILENAME=1,
        SND_ASYNC=2,
        SND_NODEFAULT=4,
        SND_ALIAS=8,
    )
    monkeypatch.setitem(sys.modules, "winsound", fake_winsound)
    monkeypatch.setenv("WINDIR", str(tmp_path))

    media_dir = tmp_path / "Media"
    media_dir.mkdir()
    expected = media_dir / "Windows Ding.wav"
    expected.write_bytes(b"wav")

    rt._play_capture_sound()

    assert calls == [(str(expected), 7)]

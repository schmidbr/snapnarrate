"""Builds the real settings window (hidden) and drives it: every page, save, discard, voices."""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from snap_narrate.config import ConfigStore, init_config
from snap_narrate.providers.elevenlabs import Voice

ctk = pytest.importorskip("customtkinter")


class FakeStartup:
    def __init__(self) -> None:
        self.enabled = False

    def is_enabled(self) -> bool:
        return self.enabled

    def set(self, enabled: bool) -> None:
        self.enabled = enabled


VOICES = [
    Voice("v1", "Clyde", "premade", (("accent", "american"), ("gender", "male")), "https://example.com/1.mp3"),
    Voice("v2", "Aria", "premade", (("accent", "american"), ("gender", "female")), "https://example.com/2.mp3"),
]


@pytest.fixture(scope="module")
def root():
    # One Tk root for all tests, like the app: CustomTkinter caches images per root.
    try:
        tk_root = ctk.CTk()
    except Exception as exc:  # noqa: BLE001 - no display available
        pytest.skip(f"Tk unavailable: {exc}")
    tk_root.withdraw()
    yield tk_root
    tk_root.destroy()


@pytest.fixture
def window(tmp_path: Path, root):  # noqa: ANN001
    from snap_narrate.ui.settings import SettingsWindow, WindowActions

    store = ConfigStore(init_config(tmp_path / "config.toml"))
    saved: list = []
    volumes: list[float] = []
    win = SettingsWindow(
        root, store, on_saved=saved.append, startup=FakeStartup(),
        actions=WindowActions(app_running=lambda: True, set_volume=volumes.append),
        voice_source=lambda _key: VOICES,
    )  # fmt: skip
    win.win.withdraw()
    win.saved, win.volumes = saved, volumes  # type: ignore[attr-defined]
    yield win
    win._closed = True
    win.win.destroy()


def pump(win, seconds: float = 0.3) -> None:  # noqa: ANN001
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        win.win.update()
        time.sleep(0.01)


def test_every_page_builds(window) -> None:  # noqa: ANN001
    from snap_narrate.ui.settings import PAGES

    for page_id, _label, _icon in PAGES:
        window.show(page_id)
        pump(window, 0.05)
        assert window._current == page_id


def test_status_reflects_missing_setup(window) -> None:  # noqa: ANN001
    pump(window)
    assert "Setup needed" in window._status_pill.cget("text")
    window.var("openai.api_key").set("sk-test")
    window.var("elevenlabs.api_key").set("sk_test")
    window.var("elevenlabs.voice_id").set("v1")
    pump(window)
    assert "Running" in window._status_pill.cget("text")


def test_voice_list_shows_names_and_selects_by_id(window) -> None:  # noqa: ANN001
    window.var("elevenlabs.api_key").set("sk_test")
    window.show("voice")
    pump(window, 0.5)
    assert [v.name for v in window._voices] == ["Clyde", "Aria"]
    window._voice_panel._choose(VOICES[1])
    assert window.var("elevenlabs.voice_id").get() == "v2"
    assert window.var("elevenlabs.voice_name").get() == "Aria"


def test_save_validates_then_writes(window) -> None:  # noqa: ANN001
    window.var("capture.cooldown_ms").set("soon")
    with pytest.raises(ValueError, match="(?i)cooldown|between captures"):
        window.collect()
    window.var("capture.cooldown_ms").set("900")
    window.var("capture.region_hotkey").set(window.var("capture.hotkey").get())
    with pytest.raises(ValueError, match="Already used"):
        window.collect()
    window.var("capture.region_hotkey").set("ctrl+shift+r")
    window.var("playback.volume").set("0.6")
    window.var("__startup__").set(True)
    assert window.dirty
    assert window.save()
    assert not window.dirty
    saved = window.store.load()
    assert saved.capture.cooldown_ms == 900 and saved.playback.volume == 0.6
    assert window.startup.enabled is True
    assert window.saved and window.volumes[-1] == pytest.approx(0.6)  # live preview reached the app


def test_discard_restores_values(window) -> None:  # noqa: ANN001
    window.var("hud.font_size").set("40")
    window.discard()
    assert window.var("hud.font_size").get() == "22" and not window.dirty


def test_switching_provider_rebuilds_reading_page(window) -> None:  # noqa: ANN001
    window.show("reading")
    first = window._pages["reading"]
    window.var("vision.provider").set("ollama-cloud")
    pump(window)
    assert window._pages["reading"] is not first
    assert "ollama_cloud.api_key" in window.titles  # the cloud fields are now on the page


def test_saving_keeps_lists_as_lists(window) -> None:  # noqa: ANN001
    """Regression: saving with no addons stored the text "[]" as an addon name."""
    assert window.var("addons.extra").get() == ""
    window.var("hud.font_size").set("30")
    assert window.save()
    assert window.store.load().addons.extra == []
    window.var("addons.extra").set("chat_log, other")
    assert window.save()
    assert window.store.load().addons.extra == ["chat_log", "other"]


def test_slider_moved_away_and_back_is_not_an_unsaved_change(window) -> None:  # noqa: ANN001
    from snap_narrate.ui.widgets import Slider

    slider = Slider(ctk.CTkFrame(window.win), window.var("playback.volume"), window.fonts, 0.1, 1.5, 0.05, str, integer=False)
    slider._moved(0.9000000000000001)
    assert window.dirty
    slider._moved(1.0000000000000002)
    assert window.var("playback.volume").get() == "1.0" and not window.dirty


def test_tray_volume_change_is_shown_and_not_undone_by_save(window) -> None:  # noqa: ANN001
    window.apply_external({"playback.volume": 0.7, "capture.mode": "region"})
    assert window.var("playback.volume").get() == "0.7" and window.var("capture.mode").get() == "region"
    assert not window.dirty
    window.var("hud.font_size").set("30")  # then an unrelated change is saved
    assert window.save()
    saved = window.store.load()
    assert saved.playback.volume == 0.7 and saved.capture.mode == "region"


def test_closing_mid_recording_gives_hotkeys_back(window) -> None:  # noqa: ANN001
    import tkinter as tk

    from snap_narrate.ui.widgets import HotkeyRecorder

    paused: list[bool] = []
    frame = ctk.CTkFrame(window.win)
    recorder = HotkeyRecorder(frame, tk.StringVar(window.win, "ctrl+shift+n"), window.fonts, lambda _s: None, paused.append)
    recorder.start()
    frame.destroy()  # the window closes while "Press a shortcut…" is showing
    assert paused == [True, False]


def test_rebuilt_pages_leave_no_dead_callbacks(window, root, monkeypatch) -> None:  # noqa: ANN001
    errors: list = []
    monkeypatch.setattr(root, "report_callback_exception", lambda *exc: errors.append(exc))
    window.show("reading")
    for provider in ("ollama-cloud", "openai", "ollama-cloud"):
        window.var("vision.provider").set(provider)
        pump(window, 0.1)
    window.var("ollama_cloud.model").set("glm-5.3-flash")
    pump(window, 0.1)
    assert errors == []
    assert len(window.var("ollama_cloud.model").trace_info()) == 2  # the window's own, and the live dropdown's


def test_home_status_is_built_from_the_form_not_the_file(window, monkeypatch) -> None:  # noqa: ANN001
    reads: list[int] = []
    original = window.store.load
    monkeypatch.setattr(window.store, "load", lambda *a, **k: reads.append(1) or original(*a, **k))
    window.show("voice")
    window.var("elevenlabs.api_key").set("sk_typed")
    pump(window, 0.4)
    assert reads == []


def test_history_page_lists_replays_copies_and_deletes(tmp_path: Path, root, monkeypatch) -> None:  # noqa: ANN001
    from snap_narrate.history import History, HistoryEntry
    from snap_narrate.ui import settings as S

    history = History(tmp_path / "history.json")
    history._entries = [
        HistoryEntry(id=str(i), time=time.time() - i, source="hotkey:fullscreen", text=f"Passage number {i}. " * 20)
        for i in range(30)
    ]
    replayed: list[str] = []
    store = ConfigStore(init_config(tmp_path / "config.toml"))
    win = S.SettingsWindow(root, store, actions=S.WindowActions(history=history, replay=replayed.append), page="history")
    win.win.withdraw()
    try:
        pump(win, 0.2)
        assert win._history_count.cget("text") == "30 passages"
        assert len(win._history_list.winfo_children()) == S.HISTORY_PAGE_SIZE + 1  # rows + "Show more"
        win._replay("3")
        assert replayed == ["3"]
        win._copy_text("hello")
        assert win.win.clipboard_get() == "hello"
        win._delete_history("0")
        assert len(history.entries()) == 29
        win._history_search.insert(0, "number 7.")
        win._render_history(reset=True)
        assert win._history_count.cget("text") == "1 of 29"
        monkeypatch.setattr(S.messagebox, "askyesno", lambda *a, **k: True)
        win._clear_history()
        assert history.entries() == []
    finally:
        win._closed = True
        win.win.destroy()

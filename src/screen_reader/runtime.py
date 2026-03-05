from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

import keyboard
import pystray
from PIL import Image
from pystray import Menu, MenuItem

from screen_reader.icon_utils import load_tray_icon
from screen_reader.capture import ScreenCapturer
from screen_reader.pipeline import NarrationPipeline
from screen_reader.startup import StartupManager


@dataclass
class RuntimeState:
    paused: bool = False


class ScreenReaderRuntime:
    def __init__(
        self,
        capturer: ScreenCapturer,
        pipeline: NarrationPipeline,
        hotkey: str,
        stop_hotkey: str,
        log_path: Path,
        game_profile: str = "default",
        config_path: Path | None = None,
        reload_callback: Callable[[Path], dict[str, Any]] | None = None,
        startup_manager: StartupManager | None = None,
        startup_notice: str | None = None,
    ) -> None:
        self.capturer = capturer
        self.pipeline = pipeline
        self.hotkey = hotkey
        self.stop_hotkey = stop_hotkey
        self.log_path = log_path
        self.game_profile = game_profile
        self.config_path = config_path
        self.reload_callback = reload_callback
        self.startup_manager = startup_manager
        self.startup_notice = startup_notice

        self.state = RuntimeState(paused=False)
        self.logger = logging.getLogger("screen_reader")

        self._running = threading.Event()
        self._running.set()
        self._work_event = threading.Event()
        self._lock = threading.Lock()
        self._pending_capture: bytes | None = None
        self._worker = threading.Thread(target=self._worker_loop, daemon=True)
        self._icon: pystray.Icon | None = None
        self._capture_hotkey_ok = False
        self._stop_hotkey_ok = False
        self._settings_open = False
        self._settings_lock = threading.Lock()
        self._config_mtime: float | None = self._read_config_mtime()
        self._last_reload_check = 0.0

    def start(self) -> None:
        self._worker.start()
        self._register_hotkeys()
        self._icon = pystray.Icon("ScreenReader", self._make_icon(), "Screen Reader", self._tray_menu())
        self._icon.run_detached()
        if self.startup_notice:
            self._notify(self.startup_notice)

        self.logger.info(
            "event=runtime_started hotkey=%s stop_hotkey=%s hotkey_ok=%s stop_hotkey_ok=%s",
            self.hotkey,
            self.stop_hotkey,
            self._capture_hotkey_ok,
            self._stop_hotkey_ok,
        )
        print(
            f"Screen Reader running. Capture: {self.hotkey}. Stop speaking: {self.stop_hotkey}. "
            "Use tray icon to pause or exit."
        )

        try:
            while self._running.is_set():
                time.sleep(0.2)
                self._check_config_reload()
        except KeyboardInterrupt:
            self.stop()

    def stop(self) -> None:
        self._running.clear()
        self._work_event.set()
        keyboard.clear_all_hotkeys()
        if self._icon:
            self._icon.stop()
        self.logger.info("event=runtime_stopped")

    def test_voice(self) -> None:
        dummy = b"dummy"
        result = self.pipeline.process_capture(dummy, self.game_profile)
        self._notify(f"Test voice: {result.message}")

    def _on_hotkey(self) -> None:
        self.logger.info("event=capture_hotkey_pressed paused=%s", self.state.paused)
        if self.state.paused:
            self.logger.info("event=capture_ignored reason=paused")
            return

        try:
            image_bytes = self.capturer.capture_png()
        except Exception as exc:  # noqa: BLE001
            self.logger.warning("event=capture_failed error=%s", exc)
            self._notify(f"Capture failed: {exc}")
            return

        with self._lock:
            self._pending_capture = image_bytes
            self._work_event.set()
        self.logger.info("event=capture_enqueued bytes=%s", len(image_bytes))

    def _worker_loop(self) -> None:
        while self._running.is_set():
            self._work_event.wait()
            self._work_event.clear()
            if not self._running.is_set():
                break

            with self._lock:
                capture = self._pending_capture
                self._pending_capture = None
                pipeline = self.pipeline

            if not capture:
                continue

            try:
                result = pipeline.process_capture(capture, self.game_profile)
            except Exception as exc:  # noqa: BLE001
                self.logger.warning("event=pipeline_exception error=%s", exc)
                self._notify(f"Narration failed: {exc}")
                continue

            self.logger.info("event=pipeline_result status=%s message=%s chars=%s", result.status, result.message, result.chars)
            if result.status != "played":
                self._notify(result.message)

    def _tray_menu(self) -> Menu:
        return Menu(
            MenuItem(lambda _: "Resume" if self.state.paused else "Pause", self._toggle_pause),
            MenuItem("Capture Now", self._tray_capture_now),
            MenuItem(lambda _: f"Run At Startup: {'On' if self._is_startup_enabled() else 'Off'}", self._tray_toggle_startup),
            MenuItem("Settings", self._tray_open_settings),
            MenuItem("Test Voice", self._tray_test_voice),
            MenuItem("Stop Speaking", self._tray_stop_speaking),
            MenuItem("Show Hotkeys", self._tray_show_hotkeys),
            MenuItem("Open Logs", self._open_logs),
            MenuItem("Exit", self._tray_exit),
        )

    def _tray_capture_now(self, icon: pystray.Icon, item: MenuItem) -> None:  # noqa: ARG002
        self._on_hotkey()

    def _tray_test_voice(self, icon: pystray.Icon, item: MenuItem) -> None:  # noqa: ARG002
        try:
            test_tone = self.pipeline.tts.synthesize("Screen Reader voice test.")
            self.pipeline.player.play(test_tone)
            self._notify("Voice test played")
        except Exception as exc:  # noqa: BLE001
            self.logger.warning("event=voice_test_failed error=%s", exc)
            self._notify(f"Voice test failed: {exc}")

    def _toggle_pause(self, icon: pystray.Icon, item: MenuItem) -> None:  # noqa: ARG002
        self.state.paused = not self.state.paused
        self.logger.info("event=pause_toggled paused=%s", self.state.paused)
        self._notify("Paused" if self.state.paused else "Resumed")

    def _on_stop_hotkey(self) -> None:
        self.logger.info("event=stop_hotkey_pressed")
        self._stop_speaking(silent=False)

    def _tray_stop_speaking(self, icon: pystray.Icon, item: MenuItem) -> None:  # noqa: ARG002
        self._stop_speaking(silent=False)

    def _stop_speaking(self, silent: bool = True) -> None:
        stop_fn = getattr(self.pipeline.player, "stop", None)
        if not callable(stop_fn):
            if not silent:
                self._notify("Stop not supported by current audio player")
            return
        try:
            stop_fn()
            self.logger.info("event=playback_stopped")
            if not silent:
                self._notify("Stopped speaking")
        except Exception as exc:  # noqa: BLE001
            self.logger.warning("event=playback_stop_failed error=%s", exc)
            if not silent:
                self._notify(f"Stop failed: {exc}")

    def _open_logs(self, icon: pystray.Icon, item: MenuItem) -> None:  # noqa: ARG002
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        if not self.log_path.exists():
            self.log_path.write_text("", encoding="utf-8")
        import os

        os.startfile(str(self.log_path))

    def _tray_exit(self, icon: pystray.Icon, item: MenuItem) -> None:  # noqa: ARG002
        self.stop()

    def _notify(self, message: str) -> None:
        if self._icon:
            try:
                self._icon.notify(message, "Screen Reader")
            except Exception:  # noqa: BLE001
                pass

    def _tray_show_hotkeys(self, icon: pystray.Icon, item: MenuItem) -> None:  # noqa: ARG002
        msg = (
            f"Capture: {self.hotkey} ({'OK' if self._capture_hotkey_ok else 'FAILED'})\n"
            f"Stop: {self.stop_hotkey} ({'OK' if self._stop_hotkey_ok else 'FAILED'})"
        )
        self._notify(msg)

    def _tray_open_settings(self, icon: pystray.Icon, item: MenuItem) -> None:  # noqa: ARG002
        if not self.config_path:
            self._notify("No config path available")
            return

        with self._settings_lock:
            if self._settings_open:
                self._notify("Settings window already open")
                return
            self._settings_open = True

        def run_settings() -> None:
            try:
                from screen_reader.ui import launch_settings_ui_with_startup

                launch_settings_ui_with_startup(self.config_path, self.startup_manager)
            except Exception as exc:  # noqa: BLE001
                self.logger.warning("event=settings_open_failed error=%s", exc)
                self._notify(f"Settings failed: {exc}")
            finally:
                with self._settings_lock:
                    self._settings_open = False
                # Force a reload check after settings window closes.
                self._check_config_reload(force=True)

        threading.Thread(target=run_settings, daemon=True).start()

    def _register_hotkeys(self) -> None:
        self._capture_hotkey_ok = False
        self._stop_hotkey_ok = False

        try:
            keyboard.add_hotkey(self.hotkey, self._on_hotkey)
            self._capture_hotkey_ok = True
        except Exception as exc:  # noqa: BLE001
            self.logger.warning("event=hotkey_register_failed kind=capture hotkey=%s error=%s", self.hotkey, exc)
            self._notify(f"Capture hotkey failed: {self.hotkey}")

        try:
            keyboard.add_hotkey(self.stop_hotkey, self._on_stop_hotkey)
            self._stop_hotkey_ok = True
        except Exception as exc:  # noqa: BLE001
            self.logger.warning("event=hotkey_register_failed kind=stop hotkey=%s error=%s", self.stop_hotkey, exc)
            self._notify(f"Stop hotkey failed: {self.stop_hotkey}")

    def _is_startup_enabled(self) -> bool:
        if not self.startup_manager:
            return False
        try:
            return self.startup_manager.is_enabled()
        except Exception:  # noqa: BLE001
            return False

    def _tray_toggle_startup(self, icon: pystray.Icon, item: MenuItem) -> None:  # noqa: ARG002
        if not self.startup_manager:
            self._notify("Startup manager unavailable")
            return
        try:
            if self.startup_manager.is_enabled():
                self.startup_manager.disable()
                self._sync_startup_state_to_config(False)
                self._notify("Run at startup disabled")
            else:
                self.startup_manager.enable()
                self._sync_startup_state_to_config(True)
                self._notify("Run at startup enabled")
        except Exception as exc:  # noqa: BLE001
            self.logger.warning("event=startup_toggle_failed error=%s", exc)
            self._notify(f"Startup toggle failed: {exc}")

    def _sync_startup_state_to_config(self, enabled: bool) -> None:
        if not self.config_path:
            return
        try:
            from screen_reader.config import load_config, save_config

            cfg = load_config(self.config_path)
            cfg.app.run_at_startup = enabled
            save_config(self.config_path, cfg)
        except Exception as exc:  # noqa: BLE001
            self.logger.warning("event=startup_config_sync_failed error=%s", exc)

    def _read_config_mtime(self) -> float | None:
        if not self.config_path:
            return None
        try:
            return self.config_path.stat().st_mtime
        except OSError:
            return None

    def _check_config_reload(self, force: bool = False) -> None:
        if not self.config_path or not self.reload_callback:
            return
        now = time.time()
        if not force and (now - self._last_reload_check) < 1.0:
            return
        self._last_reload_check = now

        current_mtime = self._read_config_mtime()
        if current_mtime is None:
            return
        if not force and self._config_mtime is not None and current_mtime <= self._config_mtime:
            return

        try:
            update = self.reload_callback(self.config_path)
            self._apply_runtime_update(update)
            self._config_mtime = current_mtime
            self.logger.info("event=config_reloaded path=%s", self.config_path)
            self._notify("Settings reloaded")
        except Exception as exc:  # noqa: BLE001
            self.logger.warning("event=config_reload_failed error=%s", exc)
            self._notify(f"Reload failed: {exc}")

    def _apply_runtime_update(self, update: dict[str, Any]) -> None:
        # Stop current playback before swapping runtime components.
        self._stop_speaking(silent=True)
        with self._lock:
            self.capturer = update.get("capturer", self.capturer)
            self.pipeline = update.get("pipeline", self.pipeline)
            self.hotkey = str(update.get("hotkey", self.hotkey))
            self.stop_hotkey = str(update.get("stop_hotkey", self.stop_hotkey))
            self.log_path = Path(update.get("log_path", self.log_path))
        keyboard.clear_all_hotkeys()
        self._register_hotkeys()

    @staticmethod
    def _make_icon() -> Image.Image:
        return load_tray_icon()

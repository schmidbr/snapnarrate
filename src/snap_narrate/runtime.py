from __future__ import annotations

import logging
import os
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

import keyboard
import pystray
from PIL import Image
from pystray import Menu, MenuItem

from snap_narrate.icon_utils import load_tray_icon
from snap_narrate.capture import Bounds, ScreenCapturer, is_valid_bounds
from snap_narrate.config import DEFAULT_CAPTURE_SOUND_NAME, WINDOWS_CAPTURE_SOUND_OPTIONS, normalize_capture_sound_name
from snap_narrate.pipeline import NarrationPipeline
from snap_narrate.region_selector import select_region_bounds
from snap_narrate.self_test import create_self_test_image_bytes
from snap_narrate.startup import StartupManager
from snap_narrate.usage import UsageService
from snap_narrate.versioning import get_app_version


@dataclass
class RuntimeState:
    paused: bool = False
    capture_mode: str = "fullscreen"


class SnapNarrateRuntime:
    def __init__(
        self,
        capturer: ScreenCapturer,
        pipeline: NarrationPipeline,
        hotkey: str,
        region_hotkey: str,
        stop_hotkey: str,
        capture_mode: str,
        min_region_px: int,
        log_path: Path,
        capture_sound_name: str = DEFAULT_CAPTURE_SOUND_NAME,
        game_profile: str = "default",
        config_path: Path | None = None,
        reload_callback: Callable[[Path], dict[str, Any]] | None = None,
        startup_manager: StartupManager | None = None,
        usage_service: UsageService | None = None,
        region_selector: Callable[[], Bounds | None] | None = None,
        startup_notice: str | None = None,
    ) -> None:
        self.capturer = capturer
        self.pipeline = pipeline
        self.hotkey = hotkey
        self.region_hotkey = region_hotkey
        self.stop_hotkey = stop_hotkey
        self.capture_sound_name = normalize_capture_sound_name(capture_sound_name)
        self.min_region_px = int(min_region_px)
        self.log_path = log_path
        self.game_profile = game_profile
        self.config_path = config_path
        self.reload_callback = reload_callback
        self.startup_manager = startup_manager
        self.usage_service = usage_service
        self.region_selector = region_selector or select_region_bounds
        self.startup_notice = startup_notice
        self.app_version = get_app_version()

        self.state = RuntimeState(paused=False, capture_mode=capture_mode if capture_mode in {"fullscreen", "region"} else "fullscreen")
        self.logger = logging.getLogger("snap_narrate")

        self._running = threading.Event()
        self._running.set()
        self._work_event = threading.Event()
        self._lock = threading.Lock()
        self._pending_capture: bytes | None = None
        self._pending_source = "unknown"
        self._pending_capture_ms = 0
        self._worker = threading.Thread(target=self._worker_loop, daemon=True)
        self._icon: pystray.Icon | None = None
        self._capture_hotkey_ok = False
        self._region_hotkey_ok = False
        self._stop_hotkey_ok = False
        self._settings_open = False
        self._settings_lock = threading.Lock()
        self._self_test_running = False
        self._self_test_lock = threading.Lock()
        self._config_mtime: float | None = self._read_config_mtime()
        self._last_reload_check = 0.0

    def start(self) -> None:
        self._worker.start()
        self._register_hotkeys()
        self._icon = pystray.Icon("SnapNarrate", self._make_icon(), "SnapNarrate", self._tray_menu())
        self._icon.run_detached()
        if self.startup_notice:
            self._notify(self.startup_notice)

        self.logger.info(
            "event=runtime_started hotkey=%s region_hotkey=%s stop_hotkey=%s mode=%s hotkey_ok=%s region_hotkey_ok=%s stop_hotkey_ok=%s",
            self.hotkey,
            self.region_hotkey,
            self.stop_hotkey,
            self.state.capture_mode,
            self._capture_hotkey_ok,
            self._region_hotkey_ok,
            self._stop_hotkey_ok,
        )
        print(
            f"SnapNarrate running. Full capture: {self.hotkey}. Region capture: {self.region_hotkey}. Stop speaking: {self.stop_hotkey}. "
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
        self.logger.info("event=fullscreen_hotkey_pressed paused=%s", self.state.paused)
        if self.state.paused:
            self.logger.info("event=capture_ignored reason=paused")
            self._notify("Capture ignored: paused")
            return
        self._notify("Hotkey pressed: capturing full screen")

        try:
            capture_start = time.perf_counter()
            image_bytes = self.capturer.capture_fullscreen_png()
            capture_ms = int(round((time.perf_counter() - capture_start) * 1000))
        except Exception as exc:  # noqa: BLE001
            self.logger.warning("event=capture_failed error=%s", exc)
            self._notify(f"Capture failed: {exc}")
            return

        self._play_capture_sound()
        self.logger.info("event=fullscreen_capture_ready capture_ms=%s bytes=%s", capture_ms, len(image_bytes))
        self._enqueue_capture(image_bytes, source="fullscreen", capture_ms=capture_ms)

    def _on_region_hotkey(self) -> None:
        self.logger.info("event=region_hotkey_pressed paused=%s", self.state.paused)
        if self.state.paused:
            self.logger.info("event=capture_ignored reason=paused")
            self._notify("Capture ignored: paused")
            return
        self._notify("Hotkey pressed: select a region")
        self._capture_region_once()

    def _worker_loop(self) -> None:
        while self._running.is_set():
            self._work_event.wait()
            self._work_event.clear()
            if not self._running.is_set():
                break

            with self._lock:
                capture = self._pending_capture
                source = self._pending_source
                capture_ms = self._pending_capture_ms
                self._pending_capture = None
                self._pending_source = "unknown"
                self._pending_capture_ms = 0
                pipeline = self.pipeline

            if not capture:
                continue

            try:
                result = pipeline.process_capture(capture, self.game_profile)
            except Exception as exc:  # noqa: BLE001
                self.logger.warning("event=pipeline_exception error=%s", exc)
                self._notify(f"Narration failed: {exc}")
                continue

            self.logger.info(
                "event=pipeline_result status=%s message=%s chars=%s source=%s capture_ms=%s",
                result.status,
                result.message,
                result.chars,
                source,
                capture_ms,
            )
            if result.timings is not None:
                self.logger.info(
                    "event=interaction_latency source=%s capture_ms=%s extract_ms=%s tts_ms=%s playback_ms=%s pipeline_ms=%s total_ms=%s",
                    source,
                    capture_ms,
                    result.timings.extract_ms,
                    result.timings.tts_ms,
                    result.timings.playback_ms,
                    result.timings.total_ms,
                    capture_ms + result.timings.total_ms,
                )
            if result.status != "played":
                self._notify(result.message)

    def _tray_menu(self) -> Menu:
        return Menu(
            MenuItem(lambda _: f"Version: {self.app_version}", lambda icon, item: None, enabled=False),
            MenuItem("Capture Now", self._tray_capture_now),
            MenuItem("Capture Region Now", self._tray_capture_region_now),
            MenuItem(lambda _: f"Capture Mode: {'Region' if self.state.capture_mode == 'region' else 'Full Screen'}", self._tray_toggle_capture_mode),
            MenuItem("Stop Speaking", self._tray_stop_speaking),
            MenuItem(lambda _: "Resume" if self.state.paused else "Pause", self._toggle_pause),
            MenuItem("Settings", self._tray_open_settings),
            MenuItem(lambda _: f"Run At Startup: {'On' if self._is_startup_enabled() else 'Off'}", self._tray_toggle_startup),
            MenuItem("Show Hotkeys", self._tray_show_hotkeys),
            MenuItem("Test Voice", self._tray_test_voice),
            MenuItem("Run Self-Test", self._tray_run_self_test),
            MenuItem("Usage & Credits", self._tray_usage_credits),
            MenuItem("Open Logs", self._open_logs),
            MenuItem("Exit", self._tray_exit),
        )

    def _tray_capture_now(self, icon: pystray.Icon, item: MenuItem) -> None:  # noqa: ARG002
        if self.state.capture_mode == "region":
            self._capture_region_once()
        else:
            self._on_hotkey()

    def _tray_capture_region_now(self, icon: pystray.Icon, item: MenuItem) -> None:  # noqa: ARG002
        self._capture_region_once()

    def _tray_toggle_capture_mode(self, icon: pystray.Icon, item: MenuItem) -> None:  # noqa: ARG002
        self.state.capture_mode = "region" if self.state.capture_mode == "fullscreen" else "fullscreen"
        self.logger.info("event=capture_mode_toggled mode=%s", self.state.capture_mode)
        self._sync_capture_mode_to_config(self.state.capture_mode)
        self._notify(f"Capture mode: {'Region' if self.state.capture_mode == 'region' else 'Full Screen'}")

    def _tray_test_voice(self, icon: pystray.Icon, item: MenuItem) -> None:  # noqa: ARG002
        try:
            test_tone = self.pipeline.tts.synthesize("SnapNarrate voice test.")
            self.pipeline.player.play(test_tone)
            self._notify("Voice test played")
        except Exception as exc:  # noqa: BLE001
            self.logger.warning("event=voice_test_failed error=%s", exc)
            self._notify(f"Voice test failed: {exc}")

    def _tray_run_self_test(self, icon: pystray.Icon, item: MenuItem) -> None:  # noqa: ARG002
        with self._self_test_lock:
            if self._self_test_running:
                self._notify("Self-test already running")
                return
            self._self_test_running = True

        def run_self_test() -> None:
            try:
                self._run_self_test()
            finally:
                with self._self_test_lock:
                    self._self_test_running = False

        threading.Thread(target=run_self_test, daemon=True).start()

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
        player = getattr(self.pipeline, "player", None)
        stop_fn = getattr(player, "stop", None)
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
                self._icon.notify(message, "SnapNarrate")
            except Exception:  # noqa: BLE001
                pass

    def _tray_show_hotkeys(self, icon: pystray.Icon, item: MenuItem) -> None:  # noqa: ARG002
        msg = (
            f"Full Capture: {self.hotkey} ({'OK' if self._capture_hotkey_ok else 'FAILED'})\n"
            f"Region Capture: {self.region_hotkey} ({'OK' if self._region_hotkey_ok else 'FAILED'})\n"
            f"Stop: {self.stop_hotkey} ({'OK' if self._stop_hotkey_ok else 'FAILED'})"
        )
        self._notify(msg)

    def _tray_usage_credits(self, icon: pystray.Icon, item: MenuItem) -> None:  # noqa: ARG002
        try:
            if self.usage_service is None:
                if not self.config_path:
                    self._notify("Usage unavailable: no config path")
                    return
                from snap_narrate.config import load_config

                self.usage_service = UsageService.from_config(load_config(self.config_path))
            snapshot = self.usage_service.get_snapshot(force_refresh=True)
            openai_msg = (
                f"OpenAI {snapshot.openai.status} "
                f"tokens={snapshot.openai.total_tokens} "
                f"cost={'n/a' if snapshot.openai.cost_usd is None else f'${snapshot.openai.cost_usd:.4f}'}"
            )
            eleven_msg = (
                f"ElevenLabs {snapshot.elevenlabs.status} "
                f"remaining={'n/a' if snapshot.elevenlabs.remaining_characters is None else snapshot.elevenlabs.remaining_characters}"
            )
            self._notify(f"{openai_msg}\n{eleven_msg}")
        except Exception as exc:  # noqa: BLE001
            self.logger.warning("event=usage_snapshot_failed error=%s", exc)
            self._notify(f"Usage fetch failed: {exc}")

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
                from snap_narrate.ui import launch_settings_ui_with_startup

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
        self._region_hotkey_ok = False
        self._stop_hotkey_ok = False

        try:
            keyboard.add_hotkey(self.hotkey, self._on_hotkey)
            self._capture_hotkey_ok = True
        except Exception as exc:  # noqa: BLE001
            self.logger.warning("event=hotkey_register_failed kind=capture hotkey=%s error=%s", self.hotkey, exc)
            self._notify(f"Capture hotkey failed: {self.hotkey}")

        try:
            keyboard.add_hotkey(self.region_hotkey, self._on_region_hotkey)
            self._region_hotkey_ok = True
        except Exception as exc:  # noqa: BLE001
            self.logger.warning("event=hotkey_register_failed kind=region hotkey=%s error=%s", self.region_hotkey, exc)
            self._notify(f"Region hotkey failed: {self.region_hotkey}")

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
            from snap_narrate.config import load_config, save_config

            cfg = load_config(self.config_path)
            cfg.app.run_at_startup = enabled
            save_config(self.config_path, cfg)
        except Exception as exc:  # noqa: BLE001
            self.logger.warning("event=startup_config_sync_failed error=%s", exc)

    def _sync_capture_mode_to_config(self, mode: str) -> None:
        if not self.config_path:
            return
        try:
            from snap_narrate.config import load_config, save_config

            cfg = load_config(self.config_path)
            cfg.capture.mode = mode
            save_config(self.config_path, cfg)
        except Exception as exc:  # noqa: BLE001
            self.logger.warning("event=capture_mode_config_sync_failed error=%s", exc)

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
            self.region_hotkey = str(update.get("region_hotkey", self.region_hotkey))
            self.stop_hotkey = str(update.get("stop_hotkey", self.stop_hotkey))
            self.capture_sound_name = normalize_capture_sound_name(
                str(update.get("capture_sound_name", self.capture_sound_name))
            )
            mode = str(update.get("capture_mode", self.state.capture_mode)).strip().lower()
            self.state.capture_mode = mode if mode in {"fullscreen", "region"} else "fullscreen"
            self.min_region_px = int(update.get("min_region_px", self.min_region_px))
            self.log_path = Path(update.get("log_path", self.log_path))
            usage_service = update.get("usage_service")
            if isinstance(usage_service, UsageService):
                self.usage_service = usage_service
        keyboard.clear_all_hotkeys()
        self._register_hotkeys()

    def _capture_region_once(self) -> None:
        if self.state.paused:
            self.logger.info("event=region_capture_ignored reason=paused")
            return
        try:
            bounds = self.region_selector()
            if not is_valid_bounds(bounds, self.min_region_px):
                self.logger.info("event=region_capture_skipped reason=invalid_or_cancelled bounds=%s", bounds)
                self._notify("Region capture cancelled or too small")
                return
            capture_start = time.perf_counter()
            image_bytes = self.capturer.capture_region_png(bounds)
            capture_ms = int(round((time.perf_counter() - capture_start) * 1000))
        except Exception as exc:  # noqa: BLE001
            self.logger.warning("event=region_capture_failed error=%s", exc)
            self._notify(f"Region capture failed: {exc}")
            return
        self.logger.info("event=region_capture_success bounds=%s capture_ms=%s", bounds, capture_ms)
        self._play_capture_sound()
        self._enqueue_capture(image_bytes, source="region", capture_ms=capture_ms)

    def _run_self_test(self) -> None:
        self.logger.info("event=self_test_started source=tray")
        self._notify("Running self-test")
        self._stop_speaking(silent=True)
        try:
            image_format = getattr(self.capturer, "image_format", "png")
            max_dimension = int(getattr(self.capturer, "max_dimension", 1400))
            jpeg_quality = int(getattr(self.capturer, "jpeg_quality", 90))
            image_bytes = create_self_test_image_bytes(
                max_dimension=max_dimension,
                image_format=image_format,
                jpeg_quality=jpeg_quality,
            )
            result = self.pipeline.process_self_test(image_bytes=image_bytes, game_profile="self-test")
        except Exception as exc:  # noqa: BLE001
            self.logger.warning("event=self_test_failed error=%s", exc)
            self._notify(f"Self-test failed: {exc}")
            return

        self.logger.info(
            "event=self_test_completed status=%s message=%s chars=%s total_ms=%s",
            result.status,
            result.message,
            result.chars,
            result.timings.total_ms if result.timings is not None else 0,
        )
        if result.status == "played":
            total_ms = result.timings.total_ms if result.timings is not None else 0
            self._notify(f"Self-test passed in {total_ms} ms")
            return
        self._notify(f"Self-test failed: {result.message}")

    def _enqueue_capture(self, image_bytes: bytes, source: str = "unknown", capture_ms: int = 0) -> None:
        with self._lock:
            self._pending_capture = image_bytes
            self._pending_source = source
            self._pending_capture_ms = int(capture_ms)
            self._work_event.set()
        self.logger.info("event=capture_enqueued bytes=%s source=%s capture_ms=%s", len(image_bytes), source, capture_ms)

    def _play_capture_sound(self) -> None:
        try:
            import winsound

            sound_path = self._capture_sound_path()
            if sound_path.exists():
                winsound.PlaySound(
                    str(sound_path),
                    winsound.SND_FILENAME | winsound.SND_ASYNC | winsound.SND_NODEFAULT,
                )
                return

            winsound.PlaySound("SystemAsterisk", winsound.SND_ALIAS | winsound.SND_ASYNC)
        except Exception as exc:  # noqa: BLE001
            self.logger.warning("event=capture_sound_failed error=%s", exc)

    def _capture_sound_path(self) -> Path:
        filename = WINDOWS_CAPTURE_SOUND_OPTIONS.get(self.capture_sound_name)
        if not filename:
            filename = WINDOWS_CAPTURE_SOUND_OPTIONS[DEFAULT_CAPTURE_SOUND_NAME]
        return Path(os.environ.get("WINDIR", r"C:\Windows")) / "Media" / filename

    @staticmethod
    def _make_icon() -> Image.Image:
        return load_tray_icon()


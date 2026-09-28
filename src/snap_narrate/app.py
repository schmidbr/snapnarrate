"""The desktop app: wires config, engine, hotkeys, tray, and addons together."""

from __future__ import annotations

import logging
import threading
from pathlib import Path

from snap_narrate.addons import AddonContext, AddonHost
from snap_narrate.config import AppConfig, ConfigStore, missing_required
from snap_narrate.engine import Engine
from snap_narrate.events import EventBus
from snap_narrate.hotkeys import HotkeyManager
from snap_narrate.logs import setup_logging
from snap_narrate.paths import user_data_dir
from snap_narrate.version import get_app_version
from snap_narrate.windows import (
    SingleInstance,
    StartupManager,
    enable_dpi_awareness,
    message_box,
    open_path,
    play_capture_sound,
)

logger = logging.getLogger("snap_narrate")

CONFIG_POLL_SEC = 1.0


class App:
    def __init__(self, config_path: Path, profile: str = "default") -> None:
        self.store = ConfigStore(config_path)
        self.profile = profile
        self.bus = EventBus()
        self.startup = StartupManager(config_path)
        self._exit = threading.Event()
        self._settings_open = False
        self._hotkey_errors: dict[str, str | None] = {}

    # ---- lifecycle --------------------------------------------------------------------

    def run(self) -> int:
        instance = SingleInstance()
        if instance.already_running:
            message_box("SnapNarrate is already running. Look for its icon in the system tray.")
            return 0

        enable_dpi_awareness()
        self.store.ensure_exists()
        cfg = self.store.load()
        setup_logging(cfg.log_path)
        logger.info("event=app_starting version=%s config=%s", get_app_version(), self.store.path)
        for warning in cfg.warnings:
            logger.warning("event=config_warning %s", warning)

        from snap_narrate.ui.region import select_region
        from snap_narrate.ui.tk_thread import TkThread
        from snap_narrate.ui.tray import Tray

        self.ui = TkThread()
        self.engine = Engine(
            cfg,
            self.bus,
            region_picker=lambda: select_region(self.ui),
            profile=self.profile,
            play_sound=play_capture_sound,
        )
        self.cfg = cfg
        self.hotkeys = HotkeyManager()
        self.tray = Tray(self)
        self.tray.start()
        self.addons = AddonHost(self._addon_context)
        self._bind_hotkeys(cfg)
        for error in self.addons.start(cfg):
            self.bus.notice(error, "warning")

        missing = missing_required(cfg)
        if missing:
            self.bus.notice(f"Welcome! Add your {', '.join(missing)} to get started.")
            self.open_settings()
        else:
            self.bus.notice(f"Ready. Press {cfg.capture.hotkey} to read the screen.")

        try:
            while not self._exit.wait(CONFIG_POLL_SEC):
                if self.store.changed_on_disk():
                    self.reload()
        except KeyboardInterrupt:
            pass
        finally:
            self._shutdown()
        return 0

    def quit(self) -> None:
        self._exit.set()

    def _shutdown(self) -> None:
        logger.info("event=app_stopping")
        for step in (self.addons.stop, self.hotkeys.stop, self.engine.close, self.tray.stop, self.ui.stop):
            try:
                step()
            except Exception:  # noqa: BLE001
                logger.exception("event=shutdown_step_failed")

    # ---- configuration ----------------------------------------------------------------

    def apply_config(self, cfg: AppConfig) -> None:
        setup_logging(cfg.log_path)
        self.engine.configure(cfg)
        self._bind_hotkeys(cfg)
        for error in self.addons.restart(cfg):
            self.bus.notice(error, "warning")
        self.cfg = cfg
        logger.info("event=config_applied")

    def reload(self) -> None:
        try:
            self.apply_config(self.store.load())
            self.bus.notice("Settings reloaded")
        except Exception as exc:  # noqa: BLE001
            logger.exception("event=config_reload_failed")
            self.bus.notice(f"Could not reload settings: {exc}", "error")

    def _bind_hotkeys(self, cfg: AppConfig) -> None:
        engine = self.engine
        self._hotkey_errors = self.hotkeys.bind(
            {
                "Capture": (cfg.capture.hotkey, lambda: engine.capture("hotkey")),
                "Region capture": (cfg.capture.region_hotkey, lambda: engine.capture_region("hotkey")),
                "Stop speaking": (cfg.capture.stop_hotkey, engine.stop_speaking),
            }
        )
        failed = [f"{name}: {error}" for name, error in self._hotkey_errors.items() if error]
        if failed:
            self.bus.notice("Some hotkeys could not be set. " + "; ".join(failed), "warning")

    def _addon_context(self, cfg: AppConfig) -> AddonContext:
        return AddonContext(engine=self.engine, bus=self.bus, config=cfg, ui=self.ui, data_dir=user_data_dir())

    # ---- tray actions -----------------------------------------------------------------

    def set_capture_mode(self, mode: str) -> None:
        self.engine.set_capture_mode(mode)
        self.store.update({"capture.mode": mode})  # our own write: not treated as an external edit

    def open_settings(self) -> None:
        if self._settings_open:
            return
        self._settings_open = True

        def closed() -> None:
            self._settings_open = False

        def build() -> None:
            from snap_narrate.ui.settings import SettingsWindow

            try:
                SettingsWindow(self.ui.root, self.store, on_saved=self._settings_saved, on_closed=closed, startup=self.startup)
            except Exception:
                closed()
                raise

        self.ui.submit(build)

    def _settings_saved(self, cfg: AppConfig) -> None:
        # Called on the Tk thread; applying config touches hotkeys and addons, so hop off it.
        threading.Thread(target=self._apply_saved, args=(cfg,), daemon=True).start()

    def _apply_saved(self, cfg: AppConfig) -> None:
        try:
            self.apply_config(cfg)
            self.bus.notice("Settings saved")
        except Exception as exc:  # noqa: BLE001
            logger.exception("event=settings_apply_failed")
            self.bus.notice(f"Settings saved, but could not be applied: {exc}", "error")

    def startup_enabled(self) -> bool:
        try:
            return self.startup.is_enabled()
        except Exception:  # noqa: BLE001
            return False

    def toggle_startup(self) -> None:
        try:
            enabled = not self.startup.is_enabled()
            self.startup.set(enabled)
            self.bus.notice("SnapNarrate will start when you sign in" if enabled else "Run at sign-in turned off")
        except Exception as exc:  # noqa: BLE001
            self.bus.notice(f"Could not change run at sign-in: {exc}", "error")

    def show_hotkeys(self) -> None:
        cfg = self.cfg
        lines = [
            f"{name}: {spec} ({'OK' if not self._hotkey_errors.get(name) else 'not available'})"
            for name, spec in (
                ("Capture", cfg.capture.hotkey),
                ("Region capture", cfg.capture.region_hotkey),
                ("Stop speaking", cfg.capture.stop_hotkey),
            )
        ]
        self.bus.notice("\n".join(lines))

    def test_voice(self) -> None:
        self.engine.speak("SnapNarrate voice test. If you can hear this, your voice is set up.", "test_voice")

    def run_self_test(self) -> None:
        def work() -> None:
            self.bus.notice("Running self-test…")
            result = self.engine.self_test()
            if result.played:
                self.bus.notice(f"Self-test passed: first audio in {result.timings.total_ms} ms")
            else:
                self.bus.notice(f"Self-test failed: {result.message}", "error")

        threading.Thread(target=work, name="snapnarrate-self-test", daemon=True).start()

    def show_usage(self) -> None:
        def work() -> None:
            from snap_narrate.usage import UsageService

            try:
                snap = UsageService.from_config(self.cfg).get_snapshot(force_refresh=True)
                cost = "n/a" if snap.openai.cost_usd is None else f"${snap.openai.cost_usd:.2f}"
                remaining = snap.elevenlabs.remaining_characters
                self.bus.notice(
                    f"OpenAI ({snap.openai.status}): {snap.openai.total_tokens:,} tokens, {cost} this month\n"
                    f"ElevenLabs ({snap.elevenlabs.status}): "
                    f"{'n/a' if remaining is None else f'{remaining:,}'} characters left"
                )
            except Exception as exc:  # noqa: BLE001
                self.bus.notice(f"Usage lookup failed: {exc}", "error")

        threading.Thread(target=work, name="snapnarrate-usage", daemon=True).start()

    def open_logs(self) -> None:
        path = self.cfg.log_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.touch(exist_ok=True)
        open_path(path)

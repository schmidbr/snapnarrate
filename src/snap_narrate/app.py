"""The desktop app: wires config, engine, hotkeys, tray, and addons together."""

from __future__ import annotations

import logging
import threading
from pathlib import Path

from snap_narrate.addons import AddonContext, AddonHost
from snap_narrate.config import AppConfig, ConfigStore, missing_required
from snap_narrate.engine import Engine
from snap_narrate.events import EventBus
from snap_narrate.history import History
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
        self._settings: object | None = None
        self.history: History | None = None
        self._hotkeys_paused = False
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
        self.history = History(cfg.history_path, cfg.history.max_items, cfg.history.enabled)
        self.history.run_id = self.engine.run_id
        self.history.attach(self.bus)
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
        if self.history is not None:
            self.history.configure(cfg.history.max_items, cfg.history.enabled)
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

    def _shortcuts(self, cfg: AppConfig) -> dict[str, tuple[str, object]]:
        engine = self.engine
        shortcuts: dict[str, tuple[str, object]] = {
            "Read screen": (cfg.capture.hotkey, lambda: engine.capture("hotkey")),
            "Read region": (cfg.capture.region_hotkey, lambda: engine.capture_region("hotkey")),
            "Stop speaking": (cfg.capture.stop_hotkey, engine.stop_speaking),
            "Replay last": (cfg.capture.replay_hotkey, self.replay_last),
            "Narration louder": (cfg.capture.volume_up_hotkey, lambda: self.nudge_volume(0.1)),
            "Narration quieter": (cfg.capture.volume_down_hotkey, lambda: self.nudge_volume(-0.1)),
        }
        return {name: binding for name, binding in shortcuts.items() if binding[0]}

    def _bind_hotkeys(self, cfg: AppConfig) -> None:
        if self._hotkeys_paused:
            return
        self._hotkey_errors = self.hotkeys.bind(self._shortcuts(cfg))  # type: ignore[arg-type]
        failed = [f"{name}: {error}" for name, error in self._hotkey_errors.items() if error]
        if failed:
            self.bus.notice("Some shortcuts could not be set. " + "; ".join(failed), "warning")

    def pause_hotkeys(self, paused: bool) -> None:
        """While Settings records a new shortcut, release ours so pressing it there is harmless."""
        self._hotkeys_paused = paused
        if paused:
            self.hotkeys.bind({})
        else:
            self._bind_hotkeys(self.cfg)

    def set_volume(self, volume: float) -> None:
        applied = self.engine.set_volume(volume)
        self.cfg.playback.volume = applied
        self.store.update({"playback.volume": round(applied, 2)})

    def nudge_volume(self, delta: float) -> None:
        self.set_volume(round(self.engine.volume + delta, 2))

    def replay_last(self) -> None:
        entry = self.history.latest() if self.history is not None else None
        if entry is None:
            self.bus.notice("Nothing to replay yet")
            return
        self.engine.replay(entry)

    def replay(self, entry_id: str) -> None:
        entry = self.history.get(entry_id) if self.history is not None else None
        if entry is not None:
            self.engine.replay(entry)

    def _addon_context(self, cfg: AppConfig) -> AddonContext:
        return AddonContext(
            engine=self.engine, bus=self.bus, config=cfg, ui=self.ui, data_dir=user_data_dir(), history=self.history
        )

    # ---- tray actions -----------------------------------------------------------------

    def set_capture_mode(self, mode: str) -> None:
        self.engine.set_capture_mode(mode)
        self.store.update({"capture.mode": mode})  # our own write: not treated as an external edit

    def open_settings(self, page: str = "home") -> None:
        def closed() -> None:
            self._settings = None

        def build() -> None:
            from snap_narrate.ui.settings import SettingsWindow, WindowActions

            if self._settings is not None:  # already open: bring it forward
                window = self._settings
                window.show(page)  # type: ignore[attr-defined]
                window._bring_forward()  # type: ignore[attr-defined]
                return
            actions = WindowActions(
                app_running=lambda: True,
                test_voice=self.test_voice,
                run_self_test=self.run_self_test,
                pause_hotkeys=lambda paused: threading.Thread(target=self.pause_hotkeys, args=(paused,), daemon=True).start(),
                set_volume=self.engine.set_volume,  # live preview; saving persists it
                history=self.history,
                replay=self.replay,
            )
            self._settings = SettingsWindow(
                self.ui.root, self.store, on_saved=self._settings_saved, on_closed=closed,
                startup=self.startup, actions=actions, page=page,
            )  # fmt: skip

        self.ui.submit(build)

    def _settings_saved(self, cfg: AppConfig) -> None:
        # Called on the Tk thread; applying config touches hotkeys and addons, so hop off it.
        threading.Thread(target=self._apply_saved, args=(cfg,), daemon=True).start()

    def _apply_saved(self, cfg: AppConfig) -> None:
        try:
            self.apply_config(cfg)  # the window itself confirms the save; no notification needed
        except Exception as exc:  # noqa: BLE001
            logger.exception("event=settings_apply_failed")
            self.bus.notice(f"Settings saved, but could not be applied: {exc}", "error")

    def show_hotkeys(self) -> None:
        from snap_narrate.hotkeys import keycaps

        lines = [
            f"{name}: {'+'.join(keycaps(spec))}{'' if not self._hotkey_errors.get(name) else ' (unavailable)'}"
            for name, (spec, _action) in self._shortcuts(self.cfg).items()
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

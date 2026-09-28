"""The SnapNarrate engine: the one object every frontend drives.

Frontends (hotkeys, tray, HUD, local API, a future Game Bar widget) call these thread-safe
commands and listen on the EventBus. The engine owns capture, the narration worker, and
the audio player, and makes sure only one narration session is live at a time.
"""

from __future__ import annotations

import logging
import threading
import time
from concurrent.futures import Future
from dataclasses import dataclass
from typing import Any, Callable

from snap_narrate import events, providers
from snap_narrate.audio import AudioPlayer
from snap_narrate.capture import Bounds, CaptureCooldown, ScreenCapturer, is_valid_bounds
from snap_narrate.config import CAPTURE_MODES, AppConfig, missing_required
from snap_narrate.events import EventBus
from snap_narrate.narrator import NarrationResult, Narrator, NarratorSettings, Session

logger = logging.getLogger("snap_narrate")

RegionPicker = Callable[[], "Bounds | None"]


@dataclass
class _Job:
    kind: str  # "image" | "text"
    payload: Any
    source: str
    dedup: bool = True
    capture_ms: int = 0
    future: Future[NarrationResult] | None = None


class Engine:
    def __init__(
        self,
        cfg: AppConfig,
        bus: EventBus | None = None,
        region_picker: RegionPicker | None = None,
        profile: str = "default",
        player: AudioPlayer | None = None,
        capturer: ScreenCapturer | None = None,
        narrator_factory: Callable[[AppConfig, AudioPlayer, EventBus], Narrator] | None = None,
        play_sound: Callable[[str], None] | None = None,
    ) -> None:
        self.bus = bus or EventBus()
        self.profile = profile
        self.region_picker = region_picker
        self._narrator_factory = narrator_factory or _default_narrator
        self._play_sound = play_sound
        self._fixed_capturer = capturer

        self._lock = threading.Lock()
        self._wake = threading.Condition(self._lock)
        self._pending: _Job | None = None
        self._session: Session | None = None
        self._next_session_id = 1
        self._running = True
        self._paused = False
        self._state = "idle"
        self._region_busy = False

        self.player = player or AudioPlayer(
            cfg.elevenlabs.output_format,
            on_chunk_start=self._on_chunk_start,
            on_progress=self._on_progress,
            on_idle=self._on_audio_idle,
        )
        self.configure(cfg)
        self._worker = threading.Thread(target=self._work, name="snapnarrate-engine", daemon=True)
        self._worker.start()

    # ---- configuration ----------------------------------------------------------------

    def configure(self, cfg: AppConfig) -> None:
        """Apply a (re)loaded config. In-flight speech is not interrupted."""
        capturer = self._fixed_capturer or ScreenCapturer(
            cooldown_ms=cfg.capture.cooldown_ms,
            max_dimension=cfg.capture.max_dimension,
            image_format=cfg.capture.image_format,
            jpeg_quality=cfg.capture.jpeg_quality,
            debug_dir=cfg.screenshot_dir if cfg.debug.save_screenshots else None,
        )
        narrator = self._narrator_factory(cfg, self.player, self.bus)
        with self._lock:
            previous = getattr(self, "narrator", None)
            if previous is not None and previous.settings.dedup_similarity_threshold == narrator.settings.dedup_similarity_threshold:
                narrator.deduper = previous.deduper  # keep "already read" memory across reloads
            self.cfg = cfg
            self.capturer = capturer
            self.narrator = narrator
            self.player.output_format = cfg.elevenlabs.output_format
            self._capture_mode = cfg.capture.mode
        self._publish_status()

    # ---- commands ---------------------------------------------------------------------

    @property
    def paused(self) -> bool:
        return self._paused

    @property
    def capture_mode(self) -> str:
        return self._capture_mode

    def status(self) -> dict[str, Any]:
        return {"state": self._state, "paused": self._paused, "capture_mode": self._capture_mode}

    def capture(self, source: str = "hotkey") -> None:
        """Capture using the current capture mode."""
        if self._capture_mode == "region":
            self.capture_region(source)
        else:
            self.capture_fullscreen(source)

    def capture_fullscreen(self, source: str = "hotkey") -> None:
        if not self._ready_to_capture():
            return
        self._set_state("capturing")
        start = time.perf_counter()
        try:
            image = self.capturer.fullscreen()
        except CaptureCooldown as exc:
            self._set_state("idle")
            self.bus.notice(str(exc))
            return
        except Exception as exc:  # noqa: BLE001
            logger.warning("event=capture_failed error=%s", exc)
            self._set_state("idle")
            self.bus.notice(f"Capture failed: {exc}", "error")
            return
        self._captured(image, f"{source}:fullscreen", start)

    def capture_region(self, source: str = "hotkey") -> None:
        """Let the user drag a region, then capture it. Returns immediately; selection
        happens on its own thread so hotkeys (e.g. Stop) keep working meanwhile."""
        if not self._ready_to_capture():
            return
        if self.region_picker is None:
            self.bus.notice("Region capture is not available here", "warning")
            return
        with self._lock:
            if self._region_busy:
                return
            self._region_busy = True
        threading.Thread(target=self._region_flow, args=(source,), name="snapnarrate-region", daemon=True).start()

    def submit_image(self, image: bytes, source: str = "api", dedup: bool = True) -> Future[NarrationResult]:
        """Narrate an image captured by someone else (an addon, the local API)."""
        return self._submit(_Job("image", image, source, dedup=dedup))

    def speak(self, text: str, source: str = "api") -> Future[NarrationResult]:
        """Speak text directly, skipping extraction."""
        return self._submit(_Job("text", text, source))

    def stop_speaking(self) -> None:
        with self._lock:
            if self._session is not None:
                self._session.cancel()
            if self._pending is not None:
                self._resolve(self._pending, NarrationResult("cancelled", "Stopped"))
                self._pending = None
        self.player.stop()
        logger.info("event=speech_stopped")

    def set_paused(self, paused: bool) -> None:
        self._paused = paused
        logger.info("event=paused value=%s", paused)
        self._publish_status()

    def toggle_pause(self) -> bool:
        self.set_paused(not self._paused)
        return self._paused

    def set_capture_mode(self, mode: str) -> None:
        if mode not in CAPTURE_MODES:
            raise ValueError(f"capture mode must be one of {CAPTURE_MODES}")
        self._capture_mode = mode
        self._publish_status()

    def self_test(self, timeout: float = 120.0) -> NarrationResult:
        from snap_narrate.self_test import create_self_test_image

        image = self.capturer.encode(create_self_test_image())
        return self._submit(_Job("image", image, "self_test", dedup=False)).result(timeout=timeout)

    def close(self) -> None:
        with self._lock:
            self._running = False
            self._wake.notify_all()
        self.stop_speaking()
        self.player.close()

    # ---- internals --------------------------------------------------------------------

    def _ready_to_capture(self) -> bool:
        if self._paused:
            self.bus.notice("Capture ignored: SnapNarrate is paused")
            return False
        missing = missing_required(self.cfg)
        if missing:
            self.bus.notice(f"Setup incomplete: add {', '.join(missing)} in Settings", "warning")
            return False
        return True

    def _region_flow(self, source: str) -> None:
        try:
            bounds = self.region_picker() if self.region_picker else None
            if not is_valid_bounds(bounds, self.cfg.capture.min_region_px):
                self.bus.notice("Region capture cancelled or too small")
                return
            assert bounds is not None
            self._set_state("capturing")
            start = time.perf_counter()
            image = self.capturer.region(bounds)
            self._captured(image, f"{source}:region", start)
        except CaptureCooldown as exc:
            self._set_state("idle")
            self.bus.notice(str(exc))
        except Exception as exc:  # noqa: BLE001
            logger.warning("event=region_capture_failed error=%s", exc)
            self._set_state("idle")
            self.bus.notice(f"Region capture failed: {exc}", "error")
        finally:
            with self._lock:
                self._region_busy = False

    def _captured(self, image: bytes, source: str, start: float) -> None:
        capture_ms = int(round((time.perf_counter() - start) * 1000))
        if self._play_sound is not None:
            self._play_sound(self.cfg.capture.sound_name)
        self.bus.publish(events.CAPTURE, source=source, bytes=len(image), capture_ms=capture_ms)
        self._submit(_Job("image", image, source, capture_ms=capture_ms))

    def _submit(self, job: _Job) -> Future[NarrationResult]:
        job.future = Future()
        with self._lock:
            if self._pending is not None:  # latest capture wins
                self._resolve(self._pending, NarrationResult("cancelled", "Superseded by a newer capture"))
            self._pending = job
            self._wake.notify_all()
        return job.future

    def _work(self) -> None:
        while True:
            with self._lock:
                self._wake.wait_for(lambda: self._pending is not None or not self._running)
                if not self._running:
                    return
                job, self._pending = self._pending, None
                if self._session is not None:
                    self._session.cancel()  # stops the previous narration's background work
                session = Session(self._next_session_id)
                self._next_session_id += 1
                self._session = session
                narrator = self.narrator
            assert job is not None
            self._run_job(job, session, narrator)

    def _run_job(self, job: _Job, session: Session, narrator: Narrator) -> None:
        self.bus.publish(events.NARRATION_STARTED, session=session.id, source=job.source)
        self._set_state("extracting" if job.kind == "image" else "speaking")
        try:
            if job.kind == "text":
                result = narrator.speak_text(str(job.payload), session)
            else:
                result = narrator.narrate(job.payload, session, self.profile, dedup=job.dedup)
        except Exception as exc:  # noqa: BLE001
            logger.warning("event=narration_failed source=%s error=%s", job.source, exc)
            result = NarrationResult("failed", str(exc))

        logger.info(
            "event=narration_result session=%s source=%s status=%s chars=%s capture_ms=%s extract_ms=%s tts_ms=%s first_audio_ms=%s message=%s",
            session.id,
            job.source,
            result.status,
            result.chars,
            job.capture_ms,
            result.timings.extract_ms,
            result.timings.tts_ms,
            job.capture_ms + result.timings.total_ms,
            result.message,
        )
        self.bus.publish(
            events.NARRATION_FINISHED,
            session=session.id,
            source=job.source,
            status=result.status,
            message=result.message,
            chars=result.chars,
            timings={"capture_ms": job.capture_ms, **result.timings.__dict__},
        )
        if not result.played and result.status != "cancelled":
            self.bus.notice(result.message, "error" if result.status == "failed" else "info")
        if self._state != "speaking":
            self._set_state("speaking" if self.player.is_playing else "idle")
        self._resolve(job, result)

    @staticmethod
    def _resolve(job: _Job, result: NarrationResult) -> None:
        if job.future is not None and not job.future.done():
            job.future.set_result(result)

    def _on_chunk_start(self, session_id: int, index: int, text: str, duration: float) -> None:
        self._set_state("speaking")
        self.bus.publish(events.SPEECH_CHUNK, session=session_id, index=index, text=text, duration=round(duration, 3))

    def _on_progress(self, session_id: int, index: int, position: float, duration: float) -> None:
        self.bus.publish(
            events.SPEECH_PROGRESS, session=session_id, index=index, position=round(position, 3), duration=round(duration, 3)
        )

    def _on_audio_idle(self) -> None:
        if self._state == "speaking":
            self._set_state("idle")
        self.bus.publish(events.SPEECH_IDLE)

    def _set_state(self, state: str) -> None:
        if state != self._state:
            self._state = state
            self._publish_status()

    def _publish_status(self) -> None:
        self.bus.publish(events.STATUS, **self.status())


def _default_narrator(cfg: AppConfig, player: AudioPlayer, bus: EventBus) -> Narrator:
    return Narrator(
        vision=providers.build_vision(cfg),
        speech=providers.build_speech(cfg),
        player=player,
        settings=NarratorSettings.from_config(cfg),
        bus=bus,
    )

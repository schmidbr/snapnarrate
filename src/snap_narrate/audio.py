"""Audio decoding and a session-aware playback queue.

Every chunk carries the narration session it belongs to. `play` starts a new session
(dropping whatever was queued), `stop` ends the current one, and `queue` silently
rejects chunks from any session that is no longer current. That is what keeps a slow
background continuation from resuming speech after Stop, or from mixing two captures.
"""

from __future__ import annotations

import io
import logging
import threading
import time
from collections import deque
from dataclasses import dataclass
from typing import Callable

import numpy as np

logger = logging.getLogger("snap_narrate")

BLOCK_FRAMES = 2048  # ~46 ms at 44.1 kHz: how quickly Stop takes effect.
PROGRESS_INTERVAL_SEC = 0.1

# tick(frames_heard) -> keep_going. Output calls it before each block (and once at the end)
# with how many frames have actually reached the speakers so far.
Tick = Callable[[int], bool]
# Narration loudness as a multiplier: 1.0 = as synthesized. Read per block, so changes apply live.
Gain = Callable[[], float]
MIN_VOLUME, MAX_VOLUME = 0.1, 1.5
# (samples, samplerate, tick, gain) -> None. Plays until done or tick() returns False.
OutputFn = Callable[[np.ndarray, int, Tick, Gain], None]


def decode_audio(data: bytes, output_format: str) -> tuple[np.ndarray, int]:
    """Decode an ElevenLabs payload to float32 samples. The sample rate for raw PCM comes
    from the format name (pcm_24000 -> 24 kHz); everything else is decoded by libsndfile."""
    if not data:
        raise RuntimeError("Empty audio payload")
    fmt = output_format.strip().lower()
    if fmt.startswith("pcm_"):
        try:
            rate = int(fmt.split("_", 1)[1])
        except ValueError as exc:
            raise RuntimeError(f"Unrecognized PCM format {output_format!r}") from exc
        usable = len(data) - (len(data) % 2)
        pcm = np.frombuffer(data[:usable], dtype="<i2")
        if pcm.size == 0:
            raise RuntimeError("No PCM samples in payload")
        return pcm.astype(np.float32) / 32768.0, rate

    import soundfile as sf

    try:
        samples, rate = sf.read(io.BytesIO(data), dtype="float32", always_2d=False)
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(f"Could not decode {output_format} audio: {exc}") from exc
    if len(samples) == 0:
        raise RuntimeError("Decoded audio has no samples")
    return samples, int(rate)


def apply_gain(block: np.ndarray, gain: float) -> np.ndarray:
    if gain == 1.0:
        return block
    return np.clip(block * gain, -1.0, 1.0)  # boosts above 100% are limited instead of wrapping


def sounddevice_output(samples: np.ndarray, rate: int, tick: Tick, gain: Gain = lambda: 1.0) -> None:
    import sounddevice as sd

    channels = 1 if samples.ndim == 1 else samples.shape[1]
    with sd.OutputStream(samplerate=rate, channels=channels, dtype="float32") as stream:
        # Frames written are ahead of what is audible by the device's output latency.
        latency_frames = int(float(stream.latency) * rate)
        for start in range(0, len(samples), BLOCK_FRAMES):
            if not tick(max(0, start - latency_frames)):
                stream.abort()
                return
            block = apply_gain(samples[start : start + BLOCK_FRAMES], gain())
            stream.write(np.ascontiguousarray(block, dtype=np.float32))
    tick(len(samples))  # the context exit waits for the buffer to drain: all of it was heard


@dataclass
class _Chunk:
    session: int
    index: int  # position within its session: 0 for the chunk passed to play(), then 1, 2, ...
    samples: np.ndarray
    rate: int
    text: str

    @property
    def duration(self) -> float:
        return len(self.samples) / float(self.rate)


class AudioPlayer:
    def __init__(
        self,
        output_format: str,
        on_chunk_start: Callable[[int, int, str, float], None] | None = None,
        on_idle: Callable[[], None] | None = None,
        output: OutputFn | None = None,
        on_progress: Callable[[int, int, float, float], None] | None = None,
    ) -> None:
        """Callbacks run on the audio thread and must be quick:
        on_chunk_start(session, index, text, duration_sec), on_progress(session, index,
        position_sec, duration_sec) about every 100 ms, on_idle() when the queue drains."""
        self.output_format = output_format
        self.volume = 1.0
        self.on_chunk_start = on_chunk_start
        self.on_progress = on_progress
        self.on_idle = on_idle
        self._output = output or sounddevice_output
        self._cond = threading.Condition()
        self._queue: deque[_Chunk] = deque()
        self._session = 0  # 0 = nothing active
        self._next_index = 0
        self._busy = False
        self._closed = False
        self._thread = threading.Thread(target=self._run, name="snapnarrate-audio", daemon=True)
        self._thread.start()

    @property
    def is_playing(self) -> bool:
        with self._cond:
            return self._busy or bool(self._queue)

    @property
    def session(self) -> int:
        return self._session

    @property
    def volume(self) -> float:
        return self._volume

    @volume.setter
    def volume(self, value: float) -> None:
        self._volume = min(max(float(value), MIN_VOLUME), MAX_VOLUME)

    def play(self, audio: bytes, session: int, text: str = "") -> None:
        """Interrupt anything playing and start `session` with this chunk."""
        samples, rate = decode_audio(audio, self.output_format)
        with self._cond:
            self._session = session
            self._queue.clear()
            self._queue.append(_Chunk(session, 0, samples, rate, text))
            self._next_index = 1
            self._cond.notify_all()

    def queue(self, audio: bytes, session: int, text: str = "") -> bool:
        """Append to `session` if it is still current. Returns False if it was dropped."""
        if session != self._session:
            return False
        samples, rate = decode_audio(audio, self.output_format)
        with self._cond:
            if session != self._session:
                return False
            self._queue.append(_Chunk(session, self._next_index, samples, rate, text))
            self._next_index += 1
            self._cond.notify_all()
            return True

    def stop(self) -> None:
        with self._cond:
            self._session = 0
            self._queue.clear()
            self._cond.notify_all()

    def close(self) -> None:
        with self._cond:
            self._closed = True
            self._session = 0
            self._queue.clear()
            self._cond.notify_all()

    def wait_idle(self, timeout: float | None = None) -> bool:
        """Block until the queue drains. For CLI self-test; returns False on timeout."""
        with self._cond:
            return self._cond.wait_for(lambda: not self._busy and not self._queue, timeout=timeout)

    def _run(self) -> None:
        while True:
            with self._cond:
                self._cond.wait_for(lambda: self._queue or self._closed)
                if self._closed:
                    return
                chunk = self._queue.popleft()
                if chunk.session != self._session:
                    continue
                self._busy = True

            if self.on_chunk_start:
                try:
                    self.on_chunk_start(chunk.session, chunk.index, chunk.text, chunk.duration)
                except Exception:  # noqa: BLE001
                    logger.exception("event=audio_chunk_callback_failed")
            try:
                self._output(chunk.samples, chunk.rate, self._make_tick(chunk), lambda: self.volume)
            except Exception as exc:  # noqa: BLE001
                logger.warning("event=audio_playback_failed error=%s", exc)

            with self._cond:
                idle = not self._queue
                if idle:
                    self._busy = False
                self._cond.notify_all()
            if idle and self.on_idle:
                try:
                    self.on_idle()
                except Exception:  # noqa: BLE001
                    logger.exception("event=audio_idle_callback_failed")

    def _make_tick(self, chunk: _Chunk) -> Tick:
        last_report = [float("-inf")]
        total = len(chunk.samples)

        def tick(frames_heard: int) -> bool:
            alive = chunk.session == self._session and not self._closed
            if alive and self.on_progress is not None:
                now = time.monotonic()
                if now - last_report[0] >= PROGRESS_INTERVAL_SEC or frames_heard >= total:
                    last_report[0] = now
                    try:
                        self.on_progress(chunk.session, chunk.index, min(frames_heard, total) / chunk.rate, chunk.duration)
                    except Exception:  # noqa: BLE001
                        logger.exception("event=audio_progress_callback_failed")
            return alive

        return tick

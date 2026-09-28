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
from collections import deque
from dataclasses import dataclass
from typing import Callable

import numpy as np

logger = logging.getLogger("snap_narrate")

BLOCK_FRAMES = 2048  # ~46 ms at 44.1 kHz: how quickly Stop takes effect.

# (samples, samplerate, keep_going) -> None. Plays until done or keep_going() is False.
OutputFn = Callable[[np.ndarray, int, Callable[[], bool]], None]


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


def sounddevice_output(samples: np.ndarray, rate: int, keep_going: Callable[[], bool]) -> None:
    import sounddevice as sd

    channels = 1 if samples.ndim == 1 else samples.shape[1]
    with sd.OutputStream(samplerate=rate, channels=channels, dtype="float32") as stream:
        for start in range(0, len(samples), BLOCK_FRAMES):
            if not keep_going():
                stream.abort()
                return
            stream.write(np.ascontiguousarray(samples[start : start + BLOCK_FRAMES], dtype=np.float32))


@dataclass
class _Chunk:
    session: int
    samples: np.ndarray
    rate: int
    text: str


class AudioPlayer:
    def __init__(
        self,
        output_format: str,
        on_chunk_start: Callable[[int, str], None] | None = None,
        on_idle: Callable[[], None] | None = None,
        output: OutputFn | None = None,
    ) -> None:
        self.output_format = output_format
        self.on_chunk_start = on_chunk_start
        self.on_idle = on_idle
        self._output = output or sounddevice_output
        self._cond = threading.Condition()
        self._queue: deque[_Chunk] = deque()
        self._session = 0  # 0 = nothing active
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

    def play(self, audio: bytes, session: int, text: str = "") -> None:
        """Interrupt anything playing and start `session` with this chunk."""
        samples, rate = decode_audio(audio, self.output_format)
        with self._cond:
            self._session = session
            self._queue.clear()
            self._queue.append(_Chunk(session, samples, rate, text))
            self._cond.notify_all()

    def queue(self, audio: bytes, session: int, text: str = "") -> bool:
        """Append to `session` if it is still current. Returns False if it was dropped."""
        if session != self._session:
            return False
        samples, rate = decode_audio(audio, self.output_format)
        with self._cond:
            if session != self._session:
                return False
            self._queue.append(_Chunk(session, samples, rate, text))
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
                    self.on_chunk_start(chunk.session, chunk.text)
                except Exception:  # noqa: BLE001
                    logger.exception("event=audio_chunk_callback_failed")
            try:
                self._output(chunk.samples, chunk.rate, lambda: chunk.session == self._session and not self._closed)
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

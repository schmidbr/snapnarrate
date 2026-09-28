from __future__ import annotations

import threading
from typing import Callable

import numpy as np
import pytest

from snap_narrate.audio import AudioPlayer
from snap_narrate.providers.base import ExtractResult

AUDIO = b"\x00\x01" * 64  # valid pcm_16000 payload


class FakeVision:
    def __init__(self, full: ExtractResult, first: ExtractResult | None = None) -> None:
        self.full = full
        self.first = first or full
        self.full_calls = 0
        self.first_calls = 0

    def extract(self, image: bytes, profile: str = "default") -> ExtractResult:
        self.full_calls += 1
        return self.full

    def extract_first(self, image: bytes, profile: str = "default") -> ExtractResult:
        self.first_calls += 1
        return self.first


class FakeSpeech:
    output_format = "pcm_16000"

    def __init__(self, fail_times: int = 0, before: Callable[[str], None] | None = None) -> None:
        self.fail_times = fail_times
        self.calls: list[tuple[str, bool]] = []
        self.before = before

    def synthesize(self, text: str, fast: bool = False) -> bytes:
        if self.before:
            self.before(text)
        self.calls.append((text, fast))
        if len(self.calls) <= self.fail_times:
            raise RuntimeError("transient")
        return AUDIO


class RecordingOutput:
    """Stands in for the sound card: records what was played, instantly."""

    def __init__(self) -> None:
        self.played: list[int] = []
        self.gate: threading.Event | None = None  # when set, playback blocks until released

    def __call__(self, samples: np.ndarray, rate: int, tick: Callable[[int], bool]) -> None:
        self.played.append(len(samples))
        if not tick(0):
            return
        if self.gate is not None:
            while tick(0) and not self.gate.wait(0.01):
                pass
            return
        tick(len(samples))


@pytest.fixture
def output() -> RecordingOutput:
    return RecordingOutput()


@pytest.fixture
def player(output: RecordingOutput):
    started: list[tuple[int, str]] = []
    p = AudioPlayer("pcm_16000", on_chunk_start=lambda s, i, t, d: started.append((s, t)), output=output)
    p.started = started  # type: ignore[attr-defined]
    yield p
    p.close()


def run_now(fn: Callable[[], None]) -> None:
    """Replacement for the narrator's background spawner: run continuation inline."""
    fn()

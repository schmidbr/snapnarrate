import threading
import time

import numpy as np
import pytest

from snap_narrate.audio import AudioPlayer, decode_audio

from conftest import AUDIO, RecordingOutput


def test_decode_pcm_uses_rate_from_format() -> None:
    samples, rate = decode_audio(b"\x00\x40" * 10 + b"\x01", "pcm_24000")
    assert rate == 24000
    assert len(samples) == 10
    assert samples.dtype == np.float32
    assert samples[0] == pytest.approx(0.5)


def test_decode_rejects_empty() -> None:
    with pytest.raises(RuntimeError):
        decode_audio(b"", "pcm_16000")


def wait_for(predicate, timeout: float = 2.0) -> bool:  # noqa: ANN001
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.005)
    return False


def test_queue_is_rejected_after_stop(player: AudioPlayer, output: RecordingOutput) -> None:
    player.play(AUDIO, session=1, text="first")
    assert wait_for(lambda: len(output.played) == 1)
    player.stop()
    assert player.queue(AUDIO, session=1, text="late") is False
    time.sleep(0.05)
    assert len(output.played) == 1


def test_queue_from_old_session_is_rejected(player: AudioPlayer) -> None:
    player.play(AUDIO, session=1)
    player.play(AUDIO, session=2)
    assert player.queue(AUDIO, session=1) is False
    assert player.queue(AUDIO, session=2) is True


def test_stop_interrupts_current_chunk(output: RecordingOutput) -> None:
    output.gate = threading.Event()  # never released: chunk plays "forever"
    idle = threading.Event()
    player = AudioPlayer("pcm_16000", on_idle=idle.set, output=output)
    try:
        player.play(AUDIO, session=1)
        assert wait_for(lambda: len(output.played) == 1)
        player.stop()
        assert idle.wait(1.0)
        assert not player.is_playing
    finally:
        player.close()


def test_progress_reports_index_and_position(output: RecordingOutput) -> None:
    reports: list[tuple[int, int, float, float]] = []
    idle = threading.Event()
    player = AudioPlayer("pcm_16000", output=output, on_progress=lambda *a: reports.append(a), on_idle=idle.set)
    try:
        player.play(AUDIO, session=7)
        assert player.queue(AUDIO, session=7)
        assert idle.wait(2)
        duration = len(AUDIO) // 2 / 16000
        finals = [r for r in reports if r[2] == pytest.approx(duration)]
        assert [r[1] for r in finals] == [0, 1]  # both chunks reached 100%, in order
        assert all(r[0] == 7 for r in reports)
    finally:
        player.close()

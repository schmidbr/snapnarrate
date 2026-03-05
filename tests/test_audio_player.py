from __future__ import annotations

import numpy as np
import pytest

from snap_narrate.elevenlabs_client import TempFileAudioPlayer


def test_audio_from_bytes_valid_even_length_pcm() -> None:
    samples, samplerate = TempFileAudioPlayer.audio_from_bytes((1).to_bytes(2, "little", signed=True) * 4)
    assert isinstance(samples, np.ndarray)
    assert samples.dtype == np.float32
    assert samples.size == 4
    assert samplerate == 44100


def test_audio_from_bytes_odd_length_trims_last_byte() -> None:
    payload = (1).to_bytes(2, "little", signed=True) * 3 + b"\x00"
    samples, _ = TempFileAudioPlayer.audio_from_bytes(payload)
    assert samples.size == 3


def test_audio_from_bytes_invalid_mp3_payload() -> None:
    with pytest.raises(RuntimeError, match="Failed to decode MP3 payload"):
        TempFileAudioPlayer.audio_from_bytes(b"ID3" + b"\x00" * 10)


import threading

import numpy as np
import pytest

from snap_narrate.audio import AudioPlayer, apply_gain
from snap_narrate.config import AppConfig, dumps_config, load_config

from conftest import AUDIO, RecordingOutput


def test_gain_scales_and_limits_instead_of_wrapping() -> None:
    block = np.array([0.5, -0.5, 0.9], dtype=np.float32)
    assert np.allclose(apply_gain(block, 0.5), [0.25, -0.25, 0.45])
    assert np.allclose(apply_gain(block, 1.5), [0.75, -0.75, 1.0])  # 1.35 clipped to 1.0
    assert apply_gain(block, 1.0) is block


def test_player_passes_live_volume_to_output(output: RecordingOutput) -> None:
    idle = threading.Event()
    player = AudioPlayer("pcm_16000", output=output, on_idle=idle.set)
    try:
        player.volume = 0.4
        player.play(AUDIO, session=1)
        assert idle.wait(2)
        assert output.gains == [pytest.approx(0.4)]
        player.volume = 9  # clamped
        assert player.volume == 1.5
    finally:
        player.close()


def test_volume_setting_is_clamped_and_saved(tmp_path) -> None:  # noqa: ANN001
    path = tmp_path / "config.toml"
    path.write_text("[playback]\nvolume = 7.0\n", encoding="utf-8")
    cfg = load_config(path, environ={})
    assert cfg.playback.volume == 1.5
    assert "volume = 1.5" in dumps_config(cfg)
    assert AppConfig().capture.volume_up_hotkey == ""  # optional shortcuts are off by default

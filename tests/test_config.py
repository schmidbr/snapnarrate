from __future__ import annotations

from pathlib import Path

from snap_narrate.config import load_config, save_config


def test_load_config_reads_stop_hotkey(tmp_path: Path) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        """
[capture]
hotkey = "ctrl+shift+n"
stop_hotkey = "ctrl+shift+x"
cooldown_ms = 1500
""".strip(),
        encoding="utf-8",
    )

    cfg = load_config(config_path)
    assert cfg.capture.hotkey == "ctrl+shift+n"
    assert cfg.capture.stop_hotkey == "ctrl+shift+x"


def test_load_config_normalizes_capture_sound_name(tmp_path: Path) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        """
[capture]
sound_name = "Windows Ding.wav"
""".strip(),
        encoding="utf-8",
    )

    cfg = load_config(config_path)
    assert cfg.capture.sound_name == "Windows Ding"


def test_save_config_round_trip(tmp_path: Path) -> None:
    config_path = tmp_path / "config.toml"
    cfg = load_config(config_path)
    cfg.vision.provider = "ollama"
    cfg.vision.timeout_sec = 45
    cfg.vision.fast_mode = False
    cfg.vision.ultra_fast_mode = False
    cfg.openai.api_key = "k1"
    cfg.openai.admin_api_key = "k1-admin"
    cfg.openai.ultra_fast_model = "gpt-4.1-nano"
    cfg.openai.base_url = "https://api.openai.com"
    cfg.ollama.base_url = "http://127.0.0.1:11434"
    cfg.ollama.model = "llava:latest"
    cfg.ollama.ultra_fast_model = "llava-fast:latest"
    cfg.ollama.num_predict = 2400
    cfg.ollama.temperature = 0.1
    cfg.ollama.top_p = 0.9
    cfg.ollama.continuation_attempts = 1
    cfg.ollama.min_paragraphs = 2
    cfg.ollama.coverage_retry_attempts = 1
    cfg.elevenlabs.api_key = "k2"
    cfg.elevenlabs.voice_id = "voice-123"
    cfg.elevenlabs.speech_fast_model_id = "eleven_flash_v2"
    cfg.capture.hotkey = "ctrl+shift+n"
    cfg.capture.mode = "region"
    cfg.capture.region_hotkey = "ctrl+shift+r"
    cfg.capture.stop_hotkey = "ctrl+shift+s"
    cfg.capture.sound_name = "Chimes"
    cfg.capture.cooldown_ms = 1800
    cfg.capture.min_region_px = 96
    cfg.capture.max_dimension = 1200
    cfg.capture.image_format = "png"
    cfg.capture.jpeg_quality = 92
    cfg.filter.min_block_chars = 160
    cfg.dedup.similarity_threshold = 0.9
    cfg.playback.retry_count = 3
    cfg.playback.speech_first_enabled = False
    cfg.playback.initial_chunk_chars = 180
    cfg.playback.followup_chunk_chars = 520
    cfg.playback.followup_min_chars = 55
    cfg.debug.save_screenshots = True
    cfg.log_file = "logs/custom.log"
    cfg.app.run_at_startup = True
    cfg.usage.openai_monthly_budget_usd = 12.5
    cfg.usage.cache_seconds = 42

    save_config(config_path, cfg)
    loaded = load_config(config_path)

    assert loaded.vision.provider == "ollama"
    assert loaded.vision.timeout_sec == 45
    assert loaded.vision.fast_mode is False
    assert loaded.vision.ultra_fast_mode is False
    assert loaded.openai.api_key == "k1"
    assert loaded.openai.admin_api_key == "k1-admin"
    assert loaded.openai.ultra_fast_model == "gpt-4.1-nano"
    assert loaded.openai.base_url == "https://api.openai.com"
    assert loaded.ollama.base_url == "http://127.0.0.1:11434"
    assert loaded.ollama.model == "llava:latest"
    assert loaded.ollama.ultra_fast_model == "llava-fast:latest"
    assert loaded.ollama.num_predict == 2400
    assert loaded.ollama.temperature == 0.1
    assert loaded.ollama.top_p == 0.9
    assert loaded.ollama.continuation_attempts == 1
    assert loaded.ollama.min_paragraphs == 2
    assert loaded.ollama.coverage_retry_attempts == 1
    assert loaded.elevenlabs.api_key == "k2"
    assert loaded.elevenlabs.voice_id == "voice-123"
    assert loaded.elevenlabs.speech_fast_model_id == "eleven_flash_v2"
    assert loaded.capture.hotkey == "ctrl+shift+n"
    assert loaded.capture.mode == "region"
    assert loaded.capture.region_hotkey == "ctrl+shift+r"
    assert loaded.capture.stop_hotkey == "ctrl+shift+s"
    assert loaded.capture.sound_name == "Chimes"
    assert loaded.capture.cooldown_ms == 1800
    assert loaded.capture.min_region_px == 96
    assert loaded.capture.max_dimension == 1200
    assert loaded.capture.image_format == "png"
    assert loaded.capture.jpeg_quality == 92
    assert loaded.filter.min_block_chars == 160
    assert loaded.dedup.similarity_threshold == 0.9
    assert loaded.playback.retry_count == 3
    assert loaded.playback.speech_first_enabled is False
    assert loaded.playback.initial_chunk_chars == 180
    assert loaded.playback.followup_chunk_chars == 520
    assert loaded.playback.followup_min_chars == 55
    assert loaded.debug.save_screenshots is True
    assert loaded.log_file == "logs/custom.log"
    assert loaded.app.run_at_startup is True
    assert loaded.usage.openai_monthly_budget_usd == 12.5
    assert loaded.usage.cache_seconds == 42


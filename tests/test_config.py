import tomllib
from pathlib import Path

from snap_narrate.config import AppConfig, ConfigStore, dumps_config, init_config, load_config, missing_required


def test_defaults_round_trip(tmp_path: Path) -> None:
    path = init_config(tmp_path / "config.toml")
    cfg = load_config(path, environ={})
    assert cfg.warnings == []
    assert cfg.vision.provider == "openai"
    assert cfg.usage.openai_monthly_budget_usd is None
    assert dumps_config(cfg) == dumps_config(AppConfig())


def test_output_is_valid_toml_with_awkward_strings(tmp_path: Path) -> None:
    cfg = AppConfig()
    cfg.openai.api_key = 'sk-"quoted"\\back\nline'
    cfg.addons.extra = ["one", "two"]
    parsed = tomllib.loads(dumps_config(cfg))
    assert parsed["openai"]["api_key"] == cfg.openai.api_key
    assert parsed["addons"]["extra"] == ["one", "two"]


def test_legacy_config_loads(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    path.write_text(
        '[capture]\nhotkey = "ctrl+alt+n"\nmode = "REGION"\nimage_format = "jpg"\n'
        '[ollama]\ncontinuation_attempts = 1\n[usage]\nopenai_monthly_budget_usd = ""\n[app]\nrun_at_startup = true\n',
        encoding="utf-8",
    )
    cfg = load_config(path, environ={})
    assert cfg.capture.hotkey == "ctrl+alt+n"
    assert cfg.capture.mode == "region"
    assert cfg.capture.image_format == "jpeg"
    assert cfg.usage.openai_monthly_budget_usd is None


def test_bad_values_fall_back_with_warnings(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    path.write_text('[capture]\ncooldown_ms = "soon"\n[elevenlabs]\noutput_format = "ulaw_8000"\n', encoding="utf-8")
    cfg = load_config(path, environ={})
    assert cfg.capture.cooldown_ms == 1500
    assert cfg.elevenlabs.output_format == "mp3_44100_128"
    assert len(cfg.warnings) == 2


def test_env_secrets_are_used_but_never_saved(tmp_path: Path) -> None:
    path = init_config(tmp_path / "config.toml")
    env = {"OPENAI_API_KEY": "sk-from-env", "SNAPNARRATE_CAPTURE_COOLDOWN_MS": "10"}
    cfg = load_config(path, environ=env)
    assert cfg.openai.api_key == "sk-from-env"
    assert cfg.capture.cooldown_ms == 10

    cfg.capture.hotkey = "ctrl+alt+x"
    path.write_text(dumps_config(cfg), encoding="utf-8")
    saved = tomllib.loads(path.read_text(encoding="utf-8"))
    assert saved["openai"]["api_key"] == ""
    assert saved["capture"]["cooldown_ms"] == 1500
    assert saved["capture"]["hotkey"] == "ctrl+alt+x"


def test_relative_paths_resolve_against_config_folder(tmp_path: Path) -> None:
    cfg = load_config(init_config(tmp_path / "cfg" / "config.toml"), environ={})
    assert cfg.log_path == tmp_path / "cfg" / "logs" / "snapnarrate.log"


def test_store_ignores_its_own_writes(tmp_path: Path) -> None:
    store = ConfigStore(tmp_path / "config.toml")
    store.ensure_exists()
    store.load(mark_seen=True)
    assert not store.changed_on_disk()
    store.update({"capture.mode": "region"})
    assert not store.changed_on_disk()
    assert store.load().capture.mode == "region"


def test_outside_edit_survives_reads_and_our_own_writes(tmp_path: Path) -> None:
    import os

    store = ConfigStore(tmp_path / "config.toml")
    store.ensure_exists()
    store.load(mark_seen=True)
    # Another process (the standalone settings window) saves a new voice.
    other = ConfigStore(store.path)
    other.update({"elevenlabs.voice_id": "new-voice"})
    stat = store.path.stat()
    os.utime(store.path, ns=(stat.st_atime_ns, stat.st_mtime_ns + 10_000_000))  # never the same tick

    store.load()  # e.g. the settings window previewing
    assert store.changed_on_disk()
    store.update({"playback.volume": 0.5})  # e.g. a volume hotkey
    assert store.changed_on_disk()  # the app still reloads and picks up the new voice
    cfg = store.load(mark_seen=True)
    assert (cfg.elevenlabs.voice_id, cfg.playback.volume) == ("new-voice", 0.5)
    assert not store.changed_on_disk()


def test_missing_required() -> None:
    cfg = AppConfig()
    assert "OpenAI API key" in missing_required(cfg)
    cfg.openai.api_key, cfg.elevenlabs.api_key, cfg.elevenlabs.voice_id = "a", "b", "c"
    assert missing_required(cfg) == []


def test_ollama_cloud_needs_key_and_env_key_is_not_saved(tmp_path: Path) -> None:
    cfg = AppConfig()
    cfg.vision.provider = "ollama-cloud"
    cfg.elevenlabs.api_key = cfg.elevenlabs.voice_id = "x"
    assert missing_required(cfg) == ["Ollama Cloud API key"]

    path = init_config(tmp_path / "config.toml")
    loaded = load_config(path, environ={"OLLAMA_API_KEY": "oc-env"})
    assert loaded.ollama_cloud.api_key == "oc-env"
    assert tomllib.loads(dumps_config(loaded))["ollama_cloud"]["api_key"] == ""


def test_invalid_addon_names_are_dropped(tmp_path: Path) -> None:
    """0.6.0's window saved an empty addon list as ["[]"]; loading must heal that."""
    path = tmp_path / "config.toml"
    path.write_text('[addons]\nextra = ["[]", "chat_log"]\n', encoding="utf-8")
    cfg = load_config(path, environ={})
    assert cfg.addons.extra == ["chat_log"]
    assert any("[]" in warning for warning in cfg.warnings)

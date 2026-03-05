from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any


DEFAULT_CONFIG_PATH = Path("config.toml")


@dataclass
class OpenAIConfig:
    api_key: str = ""
    model: str = "gpt-4.1-mini"
    base_url: str = "https://api.openai.com"


@dataclass
class VisionConfig:
    provider: str = "openai"
    timeout_sec: int = 60


@dataclass
class OllamaConfig:
    base_url: str = "http://127.0.0.1:11434"
    model: str = "llava:latest"
    keep_alive: str = "5m"
    num_predict: int = 2048
    temperature: float = 0.1
    top_p: float = 0.9
    continuation_attempts: int = 1
    min_paragraphs: int = 2
    coverage_retry_attempts: int = 1


@dataclass
class ElevenLabsConfig:
    api_key: str = ""
    voice_id: str = ""
    model_id: str = "eleven_turbo_v2_5"
    output_format: str = "mp3_44100_128"


@dataclass
class CaptureConfig:
    hotkey: str = "ctrl+shift+n"
    stop_hotkey: str = "ctrl+shift+s"
    cooldown_ms: int = 1500


@dataclass
class FilterConfig:
    min_block_chars: int = 140
    ignore_short_lines: int = 4


@dataclass
class DedupConfig:
    enabled: bool = True
    similarity_threshold: float = 0.95


@dataclass
class PlaybackConfig:
    retry_count: int = 2
    retry_backoff_ms: int = 700


@dataclass
class DebugConfig:
    save_screenshots: bool = False
    screenshot_dir: str = "debug_screenshots"


@dataclass
class AppBehaviorConfig:
    run_at_startup: bool = False


@dataclass
class AppConfig:
    vision: VisionConfig
    openai: OpenAIConfig
    ollama: OllamaConfig
    elevenlabs: ElevenLabsConfig
    capture: CaptureConfig
    filter: FilterConfig
    dedup: DedupConfig
    playback: PlaybackConfig
    debug: DebugConfig
    app: AppBehaviorConfig
    log_file: str = "logs/screen-reader.log"


def _section(data: dict[str, Any], key: str) -> dict[str, Any]:
    value = data.get(key, {})
    return value if isinstance(value, dict) else {}


def load_config(path: Path) -> AppConfig:
    content: dict[str, Any] = {}
    if path.exists():
        with path.open("rb") as f:
            content = tomllib.load(f)

    openai_data = _section(content, "openai")
    vision_data = _section(content, "vision")
    ollama_data = _section(content, "ollama")
    eleven_data = _section(content, "elevenlabs")
    capture_data = _section(content, "capture")
    filter_data = _section(content, "filter")
    dedup_data = _section(content, "dedup")
    playback_data = _section(content, "playback")
    debug_data = _section(content, "debug")
    app_data = _section(content, "app")

    cfg = AppConfig(
        vision=VisionConfig(
            provider=str(vision_data.get("provider", VisionConfig.provider)),
            timeout_sec=int(vision_data.get("timeout_sec", VisionConfig.timeout_sec)),
        ),
        openai=OpenAIConfig(
            api_key=str(openai_data.get("api_key", "")),
            model=str(openai_data.get("model", OpenAIConfig.model)),
            base_url=str(openai_data.get("base_url", OpenAIConfig.base_url)),
        ),
        ollama=OllamaConfig(
            base_url=str(ollama_data.get("base_url", OllamaConfig.base_url)),
            model=str(ollama_data.get("model", OllamaConfig.model)),
            keep_alive=str(ollama_data.get("keep_alive", OllamaConfig.keep_alive)),
            num_predict=int(ollama_data.get("num_predict", OllamaConfig.num_predict)),
            temperature=float(ollama_data.get("temperature", OllamaConfig.temperature)),
            top_p=float(ollama_data.get("top_p", OllamaConfig.top_p)),
            continuation_attempts=int(ollama_data.get("continuation_attempts", OllamaConfig.continuation_attempts)),
            min_paragraphs=int(ollama_data.get("min_paragraphs", OllamaConfig.min_paragraphs)),
            coverage_retry_attempts=int(
                ollama_data.get("coverage_retry_attempts", OllamaConfig.coverage_retry_attempts)
            ),
        ),
        elevenlabs=ElevenLabsConfig(
            api_key=str(eleven_data.get("api_key", "")),
            voice_id=str(eleven_data.get("voice_id", "")),
            model_id=str(eleven_data.get("model_id", ElevenLabsConfig.model_id)),
            output_format=str(eleven_data.get("output_format", ElevenLabsConfig.output_format)),
        ),
        capture=CaptureConfig(
            hotkey=str(capture_data.get("hotkey", CaptureConfig.hotkey)),
            stop_hotkey=str(capture_data.get("stop_hotkey", CaptureConfig.stop_hotkey)),
            cooldown_ms=int(capture_data.get("cooldown_ms", CaptureConfig.cooldown_ms)),
        ),
        filter=FilterConfig(
            min_block_chars=int(filter_data.get("min_block_chars", FilterConfig.min_block_chars)),
            ignore_short_lines=int(filter_data.get("ignore_short_lines", FilterConfig.ignore_short_lines)),
        ),
        dedup=DedupConfig(
            enabled=bool(dedup_data.get("enabled", DedupConfig.enabled)),
            similarity_threshold=float(dedup_data.get("similarity_threshold", DedupConfig.similarity_threshold)),
        ),
        playback=PlaybackConfig(
            retry_count=int(playback_data.get("retry_count", PlaybackConfig.retry_count)),
            retry_backoff_ms=int(playback_data.get("retry_backoff_ms", PlaybackConfig.retry_backoff_ms)),
        ),
        debug=DebugConfig(
            save_screenshots=bool(debug_data.get("save_screenshots", DebugConfig.save_screenshots)),
            screenshot_dir=str(debug_data.get("screenshot_dir", DebugConfig.screenshot_dir)),
        ),
        app=AppBehaviorConfig(
            run_at_startup=bool(app_data.get("run_at_startup", AppBehaviorConfig.run_at_startup)),
        ),
        log_file=str(content.get("log_file", "logs/screen-reader.log")),
    )

    cfg.openai.api_key = os.getenv("OPENAI_API_KEY", cfg.openai.api_key)
    cfg.openai.model = os.getenv("OPENAI_MODEL", cfg.openai.model)
    cfg.openai.base_url = os.getenv("OPENAI_BASE_URL", cfg.openai.base_url)

    cfg.vision.provider = os.getenv("VISION_PROVIDER", cfg.vision.provider)

    cfg.elevenlabs.api_key = os.getenv("ELEVENLABS_API_KEY", cfg.elevenlabs.api_key)
    cfg.elevenlabs.voice_id = os.getenv("ELEVENLABS_VOICE_ID", cfg.elevenlabs.voice_id)
    cfg.elevenlabs.model_id = os.getenv("ELEVENLABS_MODEL_ID", cfg.elevenlabs.model_id)
    cfg.elevenlabs.output_format = os.getenv("ELEVENLABS_OUTPUT_FORMAT", cfg.elevenlabs.output_format)

    hotkey = os.getenv("SCREEN_READER_HOTKEY")
    if hotkey:
        cfg.capture.hotkey = hotkey
    stop_hotkey = os.getenv("SCREEN_READER_STOP_HOTKEY")
    if stop_hotkey:
        cfg.capture.stop_hotkey = stop_hotkey
    cfg.ollama.base_url = os.getenv("OLLAMA_BASE_URL", cfg.ollama.base_url)
    cfg.ollama.model = os.getenv("OLLAMA_MODEL", cfg.ollama.model)
    cfg.ollama.keep_alive = os.getenv("OLLAMA_KEEP_ALIVE", cfg.ollama.keep_alive)
    cfg.ollama.num_predict = int(os.getenv("OLLAMA_NUM_PREDICT", str(cfg.ollama.num_predict)))
    cfg.ollama.temperature = float(os.getenv("OLLAMA_TEMPERATURE", str(cfg.ollama.temperature)))
    cfg.ollama.top_p = float(os.getenv("OLLAMA_TOP_P", str(cfg.ollama.top_p)))
    cfg.ollama.continuation_attempts = int(
        os.getenv("OLLAMA_CONTINUATION_ATTEMPTS", str(cfg.ollama.continuation_attempts))
    )
    cfg.ollama.min_paragraphs = int(os.getenv("OLLAMA_MIN_PARAGRAPHS", str(cfg.ollama.min_paragraphs)))
    cfg.ollama.coverage_retry_attempts = int(
        os.getenv("OLLAMA_COVERAGE_RETRY_ATTEMPTS", str(cfg.ollama.coverage_retry_attempts))
    )

    return cfg


def init_config(path: Path, force: bool = False) -> Path:
    if path.exists() and not force:
        raise FileExistsError(f"Config already exists: {path}")

    template = """# Screen Reader v2 config
log_file = "logs/screen-reader.log"

[vision]
provider = "openai"
timeout_sec = 60

[openai]
api_key = ""
model = "gpt-4.1-mini"
base_url = "https://api.openai.com"

[ollama]
base_url = "http://127.0.0.1:11434"
model = "llava:latest"
keep_alive = "5m"
num_predict = 2048
temperature = 0.1
top_p = 0.9
continuation_attempts = 1
min_paragraphs = 2
coverage_retry_attempts = 1

[elevenlabs]
api_key = ""
voice_id = ""
model_id = "eleven_turbo_v2_5"
output_format = "mp3_44100_128"

[capture]
hotkey = "ctrl+shift+n"
stop_hotkey = "ctrl+shift+s"
cooldown_ms = 1500

[filter]
min_block_chars = 140
ignore_short_lines = 4

[dedup]
enabled = true
similarity_threshold = 0.95

[playback]
retry_count = 2
retry_backoff_ms = 700

[debug]
save_screenshots = false
screenshot_dir = "debug_screenshots"

[app]
run_at_startup = false
"""
    path.write_text(template, encoding="utf-8")
    return path


def _toml_str(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f"\"{escaped}\""


def render_config(cfg: AppConfig) -> str:
    return f"""# Screen Reader v2 config
log_file = {_toml_str(cfg.log_file)}

[vision]
provider = {_toml_str(cfg.vision.provider)}
timeout_sec = {cfg.vision.timeout_sec}

[openai]
api_key = {_toml_str(cfg.openai.api_key)}
model = {_toml_str(cfg.openai.model)}
base_url = {_toml_str(cfg.openai.base_url)}

[ollama]
base_url = {_toml_str(cfg.ollama.base_url)}
model = {_toml_str(cfg.ollama.model)}
keep_alive = {_toml_str(cfg.ollama.keep_alive)}
num_predict = {cfg.ollama.num_predict}
temperature = {cfg.ollama.temperature}
top_p = {cfg.ollama.top_p}
continuation_attempts = {cfg.ollama.continuation_attempts}
min_paragraphs = {cfg.ollama.min_paragraphs}
coverage_retry_attempts = {cfg.ollama.coverage_retry_attempts}

[elevenlabs]
api_key = {_toml_str(cfg.elevenlabs.api_key)}
voice_id = {_toml_str(cfg.elevenlabs.voice_id)}
model_id = {_toml_str(cfg.elevenlabs.model_id)}
output_format = {_toml_str(cfg.elevenlabs.output_format)}

[capture]
hotkey = {_toml_str(cfg.capture.hotkey)}
stop_hotkey = {_toml_str(cfg.capture.stop_hotkey)}
cooldown_ms = {cfg.capture.cooldown_ms}

[filter]
min_block_chars = {cfg.filter.min_block_chars}
ignore_short_lines = {cfg.filter.ignore_short_lines}

[dedup]
enabled = {"true" if cfg.dedup.enabled else "false"}
similarity_threshold = {cfg.dedup.similarity_threshold}

[playback]
retry_count = {cfg.playback.retry_count}
retry_backoff_ms = {cfg.playback.retry_backoff_ms}

[debug]
save_screenshots = {"true" if cfg.debug.save_screenshots else "false"}
screenshot_dir = {_toml_str(cfg.debug.screenshot_dir)}

[app]
run_at_startup = {"true" if cfg.app.run_at_startup else "false"}
"""


def save_config(path: Path, cfg: AppConfig) -> Path:
    path.write_text(render_config(cfg), encoding="utf-8")
    return path

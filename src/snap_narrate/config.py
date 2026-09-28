from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any


DEFAULT_CONFIG_PATH = Path("config.toml")
WINDOWS_CAPTURE_SOUND_OPTIONS: dict[str, str] = {
    "Windows Balloon": "Windows Balloon.wav",
    "Windows Camera": "Windows Camera.wav",
    "Windows Ding": "Windows Ding.wav",
    "Windows Notify": "Windows Notify System Generic.wav",
    "Chimes": "chimes.wav",
    "Tada": "tada.wav",
}
DEFAULT_CAPTURE_SOUND_NAME = "Windows Balloon"


@dataclass
class OpenAIConfig:
    api_key: str = ""
    admin_api_key: str = ""
    model: str = "gpt-4.1-mini"
    ultra_fast_model: str = ""
    base_url: str = "https://api.openai.com"


@dataclass
class VisionConfig:
    provider: str = "openai"
    timeout_sec: int = 60
    fast_mode: bool = True
    ultra_fast_mode: bool = True


@dataclass
class OllamaConfig:
    base_url: str = "http://127.0.0.1:11434"
    model: str = "llava:latest"
    ultra_fast_model: str = ""
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
    speech_fast_model_id: str = ""
    output_format: str = "mp3_44100_128"


@dataclass
class CaptureConfig:
    hotkey: str = "ctrl+shift+n"
    mode: str = "fullscreen"
    region_hotkey: str = "ctrl+shift+r"
    stop_hotkey: str = "ctrl+shift+s"
    sound_name: str = DEFAULT_CAPTURE_SOUND_NAME
    cooldown_ms: int = 1500
    min_region_px: int = 64
    max_dimension: int = 1600
    image_format: str = "jpeg"
    jpeg_quality: int = 85


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
    speech_first_enabled: bool = True
    initial_chunk_chars: int = 220
    followup_chunk_chars: int = 650
    followup_min_chars: int = 60


@dataclass
class DebugConfig:
    save_screenshots: bool = False
    screenshot_dir: str = "debug_screenshots"


@dataclass
class AppBehaviorConfig:
    run_at_startup: bool = False


@dataclass
class UsageConfig:
    openai_monthly_budget_usd: float | None = None
    cache_seconds: int = 60


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
    usage: UsageConfig
    log_file: str = "logs/snapnarrate.log"


def _section(data: dict[str, Any], key: str) -> dict[str, Any]:
    value = data.get(key, {})
    return value if isinstance(value, dict) else {}


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    value = raw.strip().lower()
    if value in {"1", "true", "yes", "on"}:
        return True
    if value in {"0", "false", "no", "off"}:
        return False
    return default


def normalize_capture_sound_name(value: str) -> str:
    name = value.strip()
    if name in WINDOWS_CAPTURE_SOUND_OPTIONS:
        return name
    for option_name, filename in WINDOWS_CAPTURE_SOUND_OPTIONS.items():
        if name.lower() == filename.lower():
            return option_name
    return DEFAULT_CAPTURE_SOUND_NAME


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
    usage_data = _section(content, "usage")

    raw_budget = usage_data.get("openai_monthly_budget_usd", None)
    budget_value: float | None
    if raw_budget in (None, ""):
        budget_value = None
    else:
        budget_value = float(raw_budget)

    cfg = AppConfig(
        vision=VisionConfig(
            provider=str(vision_data.get("provider", VisionConfig.provider)),
            timeout_sec=int(vision_data.get("timeout_sec", VisionConfig.timeout_sec)),
            fast_mode=bool(vision_data.get("fast_mode", VisionConfig.fast_mode)),
            ultra_fast_mode=bool(vision_data.get("ultra_fast_mode", VisionConfig.ultra_fast_mode)),
        ),
        openai=OpenAIConfig(
            api_key=str(openai_data.get("api_key", "")),
            admin_api_key=str(openai_data.get("admin_api_key", "")),
            model=str(openai_data.get("model", OpenAIConfig.model)),
            ultra_fast_model=str(openai_data.get("ultra_fast_model", OpenAIConfig.ultra_fast_model)),
            base_url=str(openai_data.get("base_url", OpenAIConfig.base_url)),
        ),
        ollama=OllamaConfig(
            base_url=str(ollama_data.get("base_url", OllamaConfig.base_url)),
            model=str(ollama_data.get("model", OllamaConfig.model)),
            ultra_fast_model=str(ollama_data.get("ultra_fast_model", OllamaConfig.ultra_fast_model)),
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
            speech_fast_model_id=str(
                eleven_data.get("speech_fast_model_id", ElevenLabsConfig.speech_fast_model_id)
            ),
            output_format=str(eleven_data.get("output_format", ElevenLabsConfig.output_format)),
        ),
        capture=CaptureConfig(
            hotkey=str(capture_data.get("hotkey", CaptureConfig.hotkey)),
            mode=str(capture_data.get("mode", CaptureConfig.mode)).strip().lower(),
            region_hotkey=str(capture_data.get("region_hotkey", CaptureConfig.region_hotkey)),
            stop_hotkey=str(capture_data.get("stop_hotkey", CaptureConfig.stop_hotkey)),
            sound_name=normalize_capture_sound_name(
                str(capture_data.get("sound_name", CaptureConfig.sound_name))
            ),
            cooldown_ms=int(capture_data.get("cooldown_ms", CaptureConfig.cooldown_ms)),
            min_region_px=int(capture_data.get("min_region_px", CaptureConfig.min_region_px)),
            max_dimension=int(capture_data.get("max_dimension", CaptureConfig.max_dimension)),
            image_format=str(capture_data.get("image_format", CaptureConfig.image_format)).strip().lower(),
            jpeg_quality=int(capture_data.get("jpeg_quality", CaptureConfig.jpeg_quality)),
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
            speech_first_enabled=bool(
                playback_data.get("speech_first_enabled", PlaybackConfig.speech_first_enabled)
            ),
            initial_chunk_chars=int(playback_data.get("initial_chunk_chars", PlaybackConfig.initial_chunk_chars)),
            followup_chunk_chars=int(playback_data.get("followup_chunk_chars", PlaybackConfig.followup_chunk_chars)),
            followup_min_chars=int(playback_data.get("followup_min_chars", PlaybackConfig.followup_min_chars)),
        ),
        debug=DebugConfig(
            save_screenshots=bool(debug_data.get("save_screenshots", DebugConfig.save_screenshots)),
            screenshot_dir=str(debug_data.get("screenshot_dir", DebugConfig.screenshot_dir)),
        ),
        app=AppBehaviorConfig(
            run_at_startup=bool(app_data.get("run_at_startup", AppBehaviorConfig.run_at_startup)),
        ),
        usage=UsageConfig(
            openai_monthly_budget_usd=budget_value,
            cache_seconds=int(usage_data.get("cache_seconds", UsageConfig.cache_seconds)),
        ),
        log_file=str(content.get("log_file", "logs/snapnarrate.log")),
    )

    cfg.openai.api_key = os.getenv("OPENAI_API_KEY", cfg.openai.api_key)
    cfg.openai.admin_api_key = os.getenv("OPENAI_ADMIN_API_KEY", cfg.openai.admin_api_key)
    cfg.openai.model = os.getenv("OPENAI_MODEL", cfg.openai.model)
    cfg.openai.ultra_fast_model = os.getenv("OPENAI_ULTRA_FAST_MODEL", cfg.openai.ultra_fast_model)
    cfg.openai.base_url = os.getenv("OPENAI_BASE_URL", cfg.openai.base_url)

    cfg.vision.provider = os.getenv("VISION_PROVIDER", cfg.vision.provider)
    cfg.vision.fast_mode = _env_bool("VISION_FAST_MODE", cfg.vision.fast_mode)
    cfg.vision.ultra_fast_mode = _env_bool("VISION_ULTRA_FAST_MODE", cfg.vision.ultra_fast_mode)
    if cfg.capture.mode not in {"fullscreen", "region"}:
        cfg.capture.mode = "fullscreen"

    cfg.elevenlabs.api_key = os.getenv("ELEVENLABS_API_KEY", cfg.elevenlabs.api_key)
    cfg.elevenlabs.voice_id = os.getenv("ELEVENLABS_VOICE_ID", cfg.elevenlabs.voice_id)
    cfg.elevenlabs.model_id = os.getenv("ELEVENLABS_MODEL_ID", cfg.elevenlabs.model_id)
    cfg.elevenlabs.speech_fast_model_id = os.getenv(
        "ELEVENLABS_SPEECH_FAST_MODEL_ID", cfg.elevenlabs.speech_fast_model_id
    )
    cfg.elevenlabs.output_format = os.getenv("ELEVENLABS_OUTPUT_FORMAT", cfg.elevenlabs.output_format)

    hotkey = os.getenv("SNAPNARRATE_HOTKEY")
    if hotkey:
        cfg.capture.hotkey = hotkey
    stop_hotkey = os.getenv("SNAPNARRATE_STOP_HOTKEY")
    if stop_hotkey:
        cfg.capture.stop_hotkey = stop_hotkey
    cfg.capture.max_dimension = int(os.getenv("SNAPNARRATE_CAPTURE_MAX_DIMENSION", str(cfg.capture.max_dimension)))
    image_format = os.getenv("SNAPNARRATE_CAPTURE_IMAGE_FORMAT")
    if image_format:
        cfg.capture.image_format = image_format.strip().lower()
    cfg.capture.jpeg_quality = int(os.getenv("SNAPNARRATE_CAPTURE_JPEG_QUALITY", str(cfg.capture.jpeg_quality)))
    cfg.ollama.base_url = os.getenv("OLLAMA_BASE_URL", cfg.ollama.base_url)
    cfg.ollama.model = os.getenv("OLLAMA_MODEL", cfg.ollama.model)
    cfg.ollama.ultra_fast_model = os.getenv("OLLAMA_ULTRA_FAST_MODEL", cfg.ollama.ultra_fast_model)
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
    raw_budget_env = os.getenv("OPENAI_MONTHLY_BUDGET_USD")
    if raw_budget_env is not None and raw_budget_env.strip() != "":
        cfg.usage.openai_monthly_budget_usd = float(raw_budget_env)
    cfg.usage.cache_seconds = int(os.getenv("USAGE_CACHE_SECONDS", str(cfg.usage.cache_seconds)))
    cfg.playback.speech_first_enabled = _env_bool(
        "SNAPNARRATE_SPEECH_FIRST_ENABLED", cfg.playback.speech_first_enabled
    )
    cfg.playback.initial_chunk_chars = int(
        os.getenv("SNAPNARRATE_INITIAL_CHUNK_CHARS", str(cfg.playback.initial_chunk_chars))
    )
    cfg.playback.followup_chunk_chars = int(
        os.getenv("SNAPNARRATE_FOLLOWUP_CHUNK_CHARS", str(cfg.playback.followup_chunk_chars))
    )
    cfg.playback.followup_min_chars = int(
        os.getenv("SNAPNARRATE_FOLLOWUP_MIN_CHARS", str(cfg.playback.followup_min_chars))
    )

    if cfg.capture.image_format == "jpg":
        cfg.capture.image_format = "jpeg"
    if cfg.capture.image_format not in {"png", "jpeg"}:
        cfg.capture.image_format = CaptureConfig.image_format
    cfg.capture.sound_name = normalize_capture_sound_name(cfg.capture.sound_name)
    cfg.capture.max_dimension = max(cfg.capture.max_dimension, 0)
    cfg.capture.jpeg_quality = min(max(cfg.capture.jpeg_quality, 1), 100)
    cfg.playback.initial_chunk_chars = max(cfg.playback.initial_chunk_chars, 80)
    cfg.playback.followup_chunk_chars = max(cfg.playback.followup_chunk_chars, cfg.playback.initial_chunk_chars)
    cfg.playback.followup_min_chars = max(cfg.playback.followup_min_chars, 20)

    return cfg


def init_config(path: Path, force: bool = False) -> Path:
    if path.exists() and not force:
        raise FileExistsError(f"Config already exists: {path}")

    template = """# SnapNarrate v2 config
log_file = "logs/snapnarrate.log"

[vision]
provider = "openai"
timeout_sec = 60
fast_mode = true
ultra_fast_mode = true

[openai]
api_key = ""
admin_api_key = ""
model = "gpt-4.1-mini"
ultra_fast_model = ""
base_url = "https://api.openai.com"

[ollama]
base_url = "http://127.0.0.1:11434"
model = "llava:latest"
ultra_fast_model = ""
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
speech_fast_model_id = ""
output_format = "mp3_44100_128"

[capture]
hotkey = "ctrl+shift+n"
mode = "fullscreen"
region_hotkey = "ctrl+shift+r"
stop_hotkey = "ctrl+shift+s"
sound_name = "Windows Balloon"
cooldown_ms = 1500
min_region_px = 64
max_dimension = 1600
image_format = "jpeg"
jpeg_quality = 85

[filter]
min_block_chars = 140
ignore_short_lines = 4

[dedup]
enabled = true
similarity_threshold = 0.95

[playback]
retry_count = 2
retry_backoff_ms = 700
speech_first_enabled = true
initial_chunk_chars = 220
followup_chunk_chars = 650
followup_min_chars = 60

[debug]
save_screenshots = false
screenshot_dir = "debug_screenshots"

[app]
run_at_startup = false

[usage]
openai_monthly_budget_usd = ""
cache_seconds = 60
"""
    path.write_text(template, encoding="utf-8")
    return path


def _toml_str(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f"\"{escaped}\""


def render_config(cfg: AppConfig) -> str:
    return f"""# SnapNarrate v2 config
log_file = {_toml_str(cfg.log_file)}

[vision]
provider = {_toml_str(cfg.vision.provider)}
timeout_sec = {cfg.vision.timeout_sec}
fast_mode = {"true" if cfg.vision.fast_mode else "false"}
ultra_fast_mode = {"true" if cfg.vision.ultra_fast_mode else "false"}

[openai]
api_key = {_toml_str(cfg.openai.api_key)}
admin_api_key = {_toml_str(cfg.openai.admin_api_key)}
model = {_toml_str(cfg.openai.model)}
ultra_fast_model = {_toml_str(cfg.openai.ultra_fast_model)}
base_url = {_toml_str(cfg.openai.base_url)}

[ollama]
base_url = {_toml_str(cfg.ollama.base_url)}
model = {_toml_str(cfg.ollama.model)}
ultra_fast_model = {_toml_str(cfg.ollama.ultra_fast_model)}
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
speech_fast_model_id = {_toml_str(cfg.elevenlabs.speech_fast_model_id)}
output_format = {_toml_str(cfg.elevenlabs.output_format)}

[capture]
hotkey = {_toml_str(cfg.capture.hotkey)}
mode = {_toml_str(cfg.capture.mode)}
region_hotkey = {_toml_str(cfg.capture.region_hotkey)}
stop_hotkey = {_toml_str(cfg.capture.stop_hotkey)}
sound_name = {_toml_str(cfg.capture.sound_name)}
cooldown_ms = {cfg.capture.cooldown_ms}
min_region_px = {cfg.capture.min_region_px}
max_dimension = {cfg.capture.max_dimension}
image_format = {_toml_str(cfg.capture.image_format)}
jpeg_quality = {cfg.capture.jpeg_quality}

[filter]
min_block_chars = {cfg.filter.min_block_chars}
ignore_short_lines = {cfg.filter.ignore_short_lines}

[dedup]
enabled = {"true" if cfg.dedup.enabled else "false"}
similarity_threshold = {cfg.dedup.similarity_threshold}

[playback]
retry_count = {cfg.playback.retry_count}
retry_backoff_ms = {cfg.playback.retry_backoff_ms}
speech_first_enabled = {"true" if cfg.playback.speech_first_enabled else "false"}
initial_chunk_chars = {cfg.playback.initial_chunk_chars}
followup_chunk_chars = {cfg.playback.followup_chunk_chars}
followup_min_chars = {cfg.playback.followup_min_chars}

[debug]
save_screenshots = {"true" if cfg.debug.save_screenshots else "false"}
screenshot_dir = {_toml_str(cfg.debug.screenshot_dir)}

[app]
run_at_startup = {"true" if cfg.app.run_at_startup else "false"}

[usage]
openai_monthly_budget_usd = {"\"\"" if cfg.usage.openai_monthly_budget_usd is None else cfg.usage.openai_monthly_budget_usd}
cache_seconds = {cfg.usage.cache_seconds}
"""


def save_config(path: Path, cfg: AppConfig) -> Path:
    path.write_text(render_config(cfg), encoding="utf-8")
    return path


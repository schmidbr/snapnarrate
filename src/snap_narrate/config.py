"""Typed configuration backed by a TOML file.

The schema is plain dataclasses. Loading, environment overrides, and saving are all
driven generically from that schema, so adding a setting means adding one field.
"""

from __future__ import annotations

import json
import os
import threading
import tomllib
from dataclasses import dataclass, field, fields, is_dataclass
from pathlib import Path
from typing import Any, get_type_hints

WINDOWS_CAPTURE_SOUND_OPTIONS: dict[str, str] = {
    "Windows Balloon": "Windows Balloon.wav",
    "Windows Camera": "Windows Camera.wav",
    "Windows Ding": "Windows Ding.wav",
    "Windows Notify": "Windows Notify System Generic.wav",
    "Chimes": "chimes.wav",
    "Tada": "tada.wav",
    "None": "",
}
DEFAULT_CAPTURE_SOUND_NAME = "Windows Balloon"

# Formats the audio player can decode. mp3 goes through libsndfile; pcm_<rate> is raw 16-bit mono.
SUPPORTED_OUTPUT_FORMATS = [
    "mp3_44100_128",
    "mp3_44100_192",
    "mp3_44100_64",
    "mp3_22050_32",
    "pcm_16000",
    "pcm_22050",
    "pcm_24000",
    "pcm_44100",
]

VISION_PROVIDERS = ["openai", "ollama", "ollama-cloud"]
OLLAMA_CLOUD_URL = "https://ollama.com"
CAPTURE_MODES = ["fullscreen", "region"]


@dataclass
class VisionConfig:
    provider: str = "openai"
    timeout_sec: int = 60
    fast_mode: bool = True
    ultra_fast_mode: bool = True


@dataclass
class OpenAIConfig:
    api_key: str = ""
    admin_api_key: str = ""
    model: str = "gpt-4.1-mini"
    ultra_fast_model: str = ""
    base_url: str = "https://api.openai.com"


@dataclass
class OllamaConfig:
    base_url: str = "http://127.0.0.1:11434"
    model: str = "llava:latest"
    ultra_fast_model: str = ""
    keep_alive: str = "5m"
    num_predict: int = 2048
    temperature: float = 0.1
    top_p: float = 0.9
    min_paragraphs: int = 2
    coverage_retry_attempts: int = 1


@dataclass
class OllamaCloudConfig:
    # Metered Ollama Cloud (https://ollama.com): runs on Ollama's servers, so no local GPU use.
    # Tuning (num_predict, temperature, ...) is shared with [ollama].
    api_key: str = ""
    model: str = "gemma4:31b"
    ultra_fast_model: str = ""


@dataclass
class ElevenLabsConfig:
    api_key: str = ""
    voice_id: str = ""
    model_id: str = "eleven_multilingual_v2"
    speech_fast_model_id: str = ""
    output_format: str = "mp3_44100_128"


@dataclass
class CaptureConfig:
    hotkey: str = "ctrl+shift+n"
    region_hotkey: str = "ctrl+shift+r"
    stop_hotkey: str = "ctrl+shift+s"
    mode: str = "fullscreen"
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
class HudConfig:
    enabled: bool = False
    position: str = "bottom"
    font_size: int = 22
    opacity: float = 0.85
    linger_ms: int = 1500
    progress_bar: bool = True


@dataclass
class ApiConfig:
    enabled: bool = False
    port: int = 47811


@dataclass
class AddonsConfig:
    # Names of third-party addons (entry point group "snapnarrate.addons") to load.
    extra: list[str] = field(default_factory=list)


@dataclass
class DebugConfig:
    save_screenshots: bool = False
    screenshot_dir: str = "debug_screenshots"


@dataclass
class UsageConfig:
    openai_monthly_budget_usd: float | None = None
    cache_seconds: int = 60


@dataclass
class AppConfig:
    log_file: str = "logs/snapnarrate.log"
    vision: VisionConfig = field(default_factory=VisionConfig)
    openai: OpenAIConfig = field(default_factory=OpenAIConfig)
    ollama: OllamaConfig = field(default_factory=OllamaConfig)
    ollama_cloud: OllamaCloudConfig = field(default_factory=OllamaCloudConfig)
    elevenlabs: ElevenLabsConfig = field(default_factory=ElevenLabsConfig)
    capture: CaptureConfig = field(default_factory=CaptureConfig)
    filter: FilterConfig = field(default_factory=FilterConfig)
    dedup: DedupConfig = field(default_factory=DedupConfig)
    playback: PlaybackConfig = field(default_factory=PlaybackConfig)
    hud: HudConfig = field(default_factory=HudConfig)
    api: ApiConfig = field(default_factory=ApiConfig)
    addons: AddonsConfig = field(default_factory=AddonsConfig)
    debug: DebugConfig = field(default_factory=DebugConfig)
    usage: UsageConfig = field(default_factory=UsageConfig)

    # Runtime-only bookkeeping, never written to disk.
    source_path: Path | None = field(default=None, repr=False, compare=False, metadata={"transient": True})
    env_overrides: dict[str, Any] = field(default_factory=dict, repr=False, compare=False, metadata={"transient": True})
    warnings: list[str] = field(default_factory=list, repr=False, compare=False, metadata={"transient": True})

    def resolve_path(self, value: str) -> Path:
        """Relative paths in the config are relative to the config file's folder."""
        path = Path(value).expanduser()
        if path.is_absolute() or self.source_path is None:
            return path
        return self.source_path.parent / path

    @property
    def log_path(self) -> Path:
        return self.resolve_path(self.log_file)

    @property
    def screenshot_dir(self) -> Path:
        return self.resolve_path(self.debug.screenshot_dir)

    def get(self, dotted: str) -> Any:
        target: Any = self
        for part in dotted.split("."):
            target = getattr(target, part)
        return target

    def set(self, dotted: str, value: Any) -> None:
        *parents, leaf = dotted.split(".")
        target: Any = self
        for part in parents:
            target = getattr(target, part)
        setattr(target, leaf, value)


# Well-known environment variables, in addition to the generic SNAPNARRATE_<SECTION>_<KEY>.
ENV_ALIASES = {
    "OPENAI_API_KEY": "openai.api_key",
    "OPENAI_ADMIN_API_KEY": "openai.admin_api_key",
    "OPENAI_MODEL": "openai.model",
    "OPENAI_BASE_URL": "openai.base_url",
    "ELEVENLABS_API_KEY": "elevenlabs.api_key",
    "ELEVENLABS_VOICE_ID": "elevenlabs.voice_id",
    "ELEVENLABS_MODEL_ID": "elevenlabs.model_id",
    "OLLAMA_BASE_URL": "ollama.base_url",
    "OLLAMA_MODEL": "ollama.model",
    "OLLAMA_API_KEY": "ollama_cloud.api_key",
    "VISION_PROVIDER": "vision.provider",
}


def _is_transient(f: Any) -> bool:
    return bool(f.metadata.get("transient"))


def iter_settings(obj: Any = None, prefix: str = "") -> list[tuple[str, Any]]:
    """Every (dotted_path, type) pair in the schema, in declaration order."""
    cls = type(obj) if obj is not None else AppConfig
    hints = get_type_hints(cls)
    out: list[tuple[str, Any]] = []
    for f in fields(cls):
        if _is_transient(f):
            continue
        hint = hints[f.name]
        path = f"{prefix}{f.name}"
        if isinstance(hint, type) and is_dataclass(hint):
            out.extend(iter_settings(hint(), prefix=f"{path}."))
        else:
            out.append((path, hint))
    return out


def coerce(value: Any, hint: Any) -> Any:
    """Convert a raw TOML/env/UI value to the schema type. Raises ValueError on bad input."""
    if hint is bool:
        if isinstance(value, bool):
            return value
        lowered = str(value).strip().lower()
        if lowered in {"1", "true", "yes", "on"}:
            return True
        if lowered in {"0", "false", "no", "off"}:
            return False
        raise ValueError(f"expected true/false, got {value!r}")
    if hint is int:
        if isinstance(value, bool):
            raise ValueError(f"expected integer, got {value!r}")
        return int(str(value).strip()) if isinstance(value, str) else int(value)
    if hint is float:
        return float(value)
    if hint is str:
        return str(value)
    if hint == (float | None):
        if value is None or (isinstance(value, str) and value.strip() == ""):
            return None
        return float(value)
    if hint == list[str]:
        if isinstance(value, str):
            return [part.strip() for part in value.split(",") if part.strip()]
        return [str(item) for item in value]
    raise ValueError(f"unsupported setting type {hint!r}")


def normalize_capture_sound_name(value: str) -> str:
    name = value.strip()
    if name in WINDOWS_CAPTURE_SOUND_OPTIONS:
        return name
    for option_name, filename in WINDOWS_CAPTURE_SOUND_OPTIONS.items():
        if filename and name.lower() == filename.lower():
            return option_name
    return DEFAULT_CAPTURE_SOUND_NAME


def _normalize(cfg: AppConfig) -> None:
    def pick(value: str, allowed: list[str], default: str, name: str) -> str:
        cleaned = value.strip().lower()
        if cleaned in allowed:
            return cleaned
        cfg.warnings.append(f"{name}: {value!r} is not one of {allowed}; using {default!r}")
        return default

    # Not restricted to VISION_PROVIDERS: addons may register more providers.
    cfg.vision.provider = cfg.vision.provider.strip().lower() or "openai"
    cfg.capture.mode = pick(cfg.capture.mode, CAPTURE_MODES, "fullscreen", "capture.mode")
    if cfg.capture.image_format.strip().lower() == "jpg":
        cfg.capture.image_format = "jpeg"
    cfg.capture.image_format = pick(cfg.capture.image_format, ["jpeg", "png"], "jpeg", "capture.image_format")
    cfg.capture.sound_name = normalize_capture_sound_name(cfg.capture.sound_name)
    cfg.elevenlabs.output_format = pick(
        cfg.elevenlabs.output_format, SUPPORTED_OUTPUT_FORMATS, "mp3_44100_128", "elevenlabs.output_format"
    )
    cfg.hud.position = pick(cfg.hud.position, ["top", "bottom"], "bottom", "hud.position")

    cfg.vision.timeout_sec = max(cfg.vision.timeout_sec, 5)
    cfg.capture.max_dimension = max(cfg.capture.max_dimension, 0)
    cfg.capture.jpeg_quality = min(max(cfg.capture.jpeg_quality, 1), 100)
    cfg.capture.min_region_px = max(cfg.capture.min_region_px, 8)
    cfg.capture.cooldown_ms = max(cfg.capture.cooldown_ms, 0)
    cfg.dedup.similarity_threshold = min(max(cfg.dedup.similarity_threshold, 0.0), 1.0)
    cfg.playback.retry_count = max(cfg.playback.retry_count, 0)
    cfg.playback.initial_chunk_chars = max(cfg.playback.initial_chunk_chars, 80)
    cfg.playback.followup_chunk_chars = max(cfg.playback.followup_chunk_chars, cfg.playback.initial_chunk_chars)
    cfg.playback.followup_min_chars = max(cfg.playback.followup_min_chars, 20)
    cfg.hud.font_size = min(max(cfg.hud.font_size, 10), 72)
    cfg.hud.opacity = min(max(cfg.hud.opacity, 0.2), 1.0)
    if not 1024 <= cfg.api.port <= 65535:
        cfg.warnings.append(f"api.port: {cfg.api.port} out of range; using 47811")
        cfg.api.port = 47811


def _env_overrides(environ: dict[str, str]) -> dict[str, str]:
    known = {path for path, _ in iter_settings()}
    found: dict[str, str] = {}
    for name, path in ENV_ALIASES.items():
        if environ.get(name):
            found[path] = environ[name]
    for path in known:
        env_name = "SNAPNARRATE_" + path.replace(".", "_").upper()
        if env_name in environ:
            found[path] = environ[env_name]
    return found


def load_config(path: Path, environ: dict[str, str] | None = None) -> AppConfig:
    cfg = AppConfig(source_path=path)
    raw: dict[str, Any] = {}
    if path.exists():
        with path.open("rb") as handle:
            raw = tomllib.load(handle)

    for dotted, hint in iter_settings():
        section, _, key = dotted.rpartition(".")
        container = raw.get(section, {}) if section else raw
        if not isinstance(container, dict) or key not in container:
            continue
        try:
            cfg.set(dotted, coerce(container[key], hint))
        except (TypeError, ValueError) as exc:
            cfg.warnings.append(f"{dotted}: {exc}; using default")

    hints = dict(iter_settings())
    for dotted, value in _env_overrides(dict(os.environ) if environ is None else environ).items():
        try:
            file_value = cfg.get(dotted)
            cfg.set(dotted, coerce(value, hints[dotted]))
            cfg.env_overrides[dotted] = file_value
        except (TypeError, ValueError) as exc:
            cfg.warnings.append(f"environment override for {dotted}: {exc}")

    _normalize(cfg)
    return cfg


def _toml_value(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return repr(value)
    if isinstance(value, list):
        return "[" + ", ".join(_toml_value(item) for item in value) + "]"
    # JSON string escapes are a valid subset of TOML basic-string escapes.
    return json.dumps(str(value), ensure_ascii=False)


def dumps_config(cfg: AppConfig) -> str:
    """Serialize to TOML. Values that came from environment variables are written as the
    file's original value so secrets supplied via env never land on disk."""
    sections: dict[str, list[str]] = {"": []}
    for dotted, _ in iter_settings():
        value = cfg.env_overrides.get(dotted, cfg.get(dotted))
        if value is None:
            continue
        section, _, key = dotted.rpartition(".")
        sections.setdefault(section, []).append(f"{key} = {_toml_value(value)}")

    parts = ["# SnapNarrate configuration. Relative paths are relative to this file.\n"]
    parts.extend(line + "\n" for line in sections.pop(""))
    for section, lines in sections.items():
        parts.append(f"\n[{section}]\n")
        parts.extend(line + "\n" for line in lines)
    return "".join(parts)


def save_config(path: Path, cfg: AppConfig) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(dumps_config(cfg), encoding="utf-8")
    os.replace(tmp, path)


def init_config(path: Path, force: bool = False) -> Path:
    if path.exists() and not force:
        raise FileExistsError(f"Config already exists: {path}")
    save_config(path, AppConfig(source_path=path))
    return path


def missing_required(cfg: AppConfig) -> list[str]:
    missing: list[str] = []
    if not cfg.elevenlabs.api_key:
        missing.append("ElevenLabs API key")
    if not cfg.elevenlabs.voice_id:
        missing.append("ElevenLabs voice")
    if cfg.vision.provider == "openai" and not cfg.openai.api_key:
        missing.append("OpenAI API key")
    if cfg.vision.provider == "ollama" and not cfg.ollama.model:
        missing.append("Ollama model")
    if cfg.vision.provider == "ollama-cloud" and not cfg.ollama_cloud.api_key:
        missing.append("Ollama Cloud API key")
    return missing


class ConfigStore:
    """Owns the config file. Tracks its own writes so they are not mistaken for external edits."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = threading.Lock()
        self._known_mtime: float | None = None

    def _mtime(self) -> float | None:
        try:
            return self.path.stat().st_mtime
        except OSError:
            return None

    def ensure_exists(self) -> None:
        if not self.path.exists():
            init_config(self.path)

    def load(self) -> AppConfig:
        with self._lock:
            cfg = load_config(self.path)
            self._known_mtime = self._mtime()
            return cfg

    def save(self, cfg: AppConfig) -> None:
        with self._lock:
            save_config(self.path, cfg)
            self._known_mtime = self._mtime()

    def update(self, changes: dict[str, Any]) -> AppConfig:
        """Load, apply {dotted.path: value} changes, save. Returns the saved config."""
        cfg = self.load()
        for dotted, value in changes.items():
            cfg.set(dotted, value)
        self.save(cfg)
        return cfg

    def changed_on_disk(self) -> bool:
        with self._lock:
            current = self._mtime()
            return current is not None and current != self._known_mtime

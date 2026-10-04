"""Provider registry.

Built-in providers are registered here; addons can call `register_vision` /
`register_speech` to add their own (e.g. a local OCR engine or another TTS service),
then select them with `vision.provider` in the config.
"""

from __future__ import annotations

from typing import Callable

from snap_narrate.config import OLLAMA_CLOUD_URL, AppConfig
from snap_narrate.providers.base import ExtractResult, SpeechProvider, VisionProvider

VisionFactory = Callable[[AppConfig], VisionProvider]
SpeechFactory = Callable[[AppConfig], SpeechProvider]

_VISION: dict[str, VisionFactory] = {}
_SPEECH: dict[str, SpeechFactory] = {}


def register_vision(name: str, factory: VisionFactory) -> None:
    _VISION[name.lower()] = factory


def register_speech(name: str, factory: SpeechFactory) -> None:
    _SPEECH[name.lower()] = factory


def vision_names() -> list[str]:
    return sorted(_VISION)


def build_vision(cfg: AppConfig) -> VisionProvider:
    factory = _VISION.get(cfg.vision.provider.lower())
    if factory is None:
        raise ValueError(f"Unknown vision provider {cfg.vision.provider!r}. Available: {', '.join(vision_names())}")
    return factory(cfg)


def build_speech(cfg: AppConfig, name: str = "elevenlabs") -> SpeechProvider:
    factory = _SPEECH.get(name.lower())
    if factory is None:
        raise ValueError(f"Unknown speech provider {name!r}")
    return factory(cfg)


def _openai(cfg: AppConfig) -> VisionProvider:
    from snap_narrate.providers.openai import OpenAIVision

    return OpenAIVision(
        api_key=cfg.openai.api_key,
        model=cfg.openai.model,
        ignore_short_lines=cfg.filter.ignore_short_lines,
        timeout_sec=cfg.vision.timeout_sec,
        base_url=cfg.openai.base_url,
        fast_mode=cfg.vision.fast_mode,
        ultra_fast_mode=cfg.vision.ultra_fast_mode,
        ultra_fast_model=cfg.openai.ultra_fast_model,
    )


def _ollama(cfg: AppConfig) -> VisionProvider:
    from snap_narrate.providers.ollama import OllamaVision

    return OllamaVision(
        base_url=cfg.ollama.base_url,
        model=cfg.ollama.model,
        ignore_short_lines=cfg.filter.ignore_short_lines,
        timeout_sec=cfg.vision.timeout_sec,
        keep_alive=cfg.ollama.keep_alive,
        num_predict=cfg.ollama.num_predict,
        temperature=cfg.ollama.temperature,
        top_p=cfg.ollama.top_p,
        min_paragraphs=cfg.ollama.min_paragraphs,
        coverage_retry_attempts=cfg.ollama.coverage_retry_attempts,
        fast_mode=cfg.vision.fast_mode,
        ultra_fast_mode=cfg.vision.ultra_fast_mode,
        ultra_fast_model=cfg.ollama.ultra_fast_model,
    )


def _ollama_cloud(cfg: AppConfig) -> VisionProvider:
    from snap_narrate.providers.ollama import OllamaVision

    return OllamaVision(
        base_url=OLLAMA_CLOUD_URL,
        model=cfg.ollama_cloud.model,
        api_key=cfg.ollama_cloud.api_key,
        ignore_short_lines=cfg.filter.ignore_short_lines,
        timeout_sec=cfg.vision.timeout_sec,
        num_predict=cfg.ollama.num_predict,
        temperature=cfg.ollama.temperature,
        top_p=cfg.ollama.top_p,
        min_paragraphs=cfg.ollama.min_paragraphs,
        coverage_retry_attempts=cfg.ollama.coverage_retry_attempts,
        fast_mode=cfg.vision.fast_mode,
        ultra_fast_mode=cfg.vision.ultra_fast_mode,
        ultra_fast_model=cfg.ollama_cloud.ultra_fast_model,
    )


def _elevenlabs(cfg: AppConfig) -> SpeechProvider:
    from snap_narrate.providers.elevenlabs import ElevenLabsSpeech

    return ElevenLabsSpeech(
        api_key=cfg.elevenlabs.api_key,
        voice_id=cfg.elevenlabs.voice_id,
        model_id=cfg.elevenlabs.model_id,
        speech_fast_model_id=cfg.elevenlabs.speech_fast_model_id,
        output_format=cfg.elevenlabs.output_format,
    )


register_vision("openai", _openai)
register_vision("ollama", _ollama)
register_vision("ollama-cloud", _ollama_cloud)
register_speech("elevenlabs", _elevenlabs)

__all__ = [
    "ExtractResult",
    "SpeechProvider",
    "VisionProvider",
    "build_speech",
    "build_vision",
    "register_speech",
    "register_vision",
    "vision_names",
]

from __future__ import annotations

from snap_narrate.config import AppConfig
from snap_narrate.openai_client import OllamaVisionExtractor, OpenAIVisionExtractor
from snap_narrate.pipeline import VisionExtractor


def build_extractor(cfg: AppConfig) -> VisionExtractor:
    provider = cfg.vision.provider.strip().lower()
    if provider == "openai":
        return OpenAIVisionExtractor(
            api_key=cfg.openai.api_key,
            model=cfg.openai.model,
            ignore_short_lines=cfg.filter.ignore_short_lines,
            timeout_sec=cfg.vision.timeout_sec,
            base_url=cfg.openai.base_url,
        )
    if provider == "ollama":
        return OllamaVisionExtractor(
            base_url=cfg.ollama.base_url,
            model=cfg.ollama.model,
            ignore_short_lines=cfg.filter.ignore_short_lines,
            timeout_sec=cfg.vision.timeout_sec,
            keep_alive=cfg.ollama.keep_alive,
            num_predict=cfg.ollama.num_predict,
            temperature=cfg.ollama.temperature,
            top_p=cfg.ollama.top_p,
            continuation_attempts=cfg.ollama.continuation_attempts,
            min_paragraphs=cfg.ollama.min_paragraphs,
            coverage_retry_attempts=cfg.ollama.coverage_retry_attempts,
        )
    raise ValueError(f"Unsupported vision.provider: {cfg.vision.provider}")


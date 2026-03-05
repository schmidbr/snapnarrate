from __future__ import annotations

from pathlib import Path

import pytest

from snap_narrate.config import load_config
from snap_narrate.extractor_factory import build_extractor
from snap_narrate.openai_client import OllamaVisionExtractor, OpenAIVisionExtractor


def test_factory_builds_openai_by_default(tmp_path: Path) -> None:
    cfg = load_config(tmp_path / "config.toml")
    extractor = build_extractor(cfg)
    assert isinstance(extractor, OpenAIVisionExtractor)


def test_factory_builds_ollama_when_selected(tmp_path: Path) -> None:
    cfg = load_config(tmp_path / "config.toml")
    cfg.vision.provider = "ollama"
    extractor = build_extractor(cfg)
    assert isinstance(extractor, OllamaVisionExtractor)


def test_factory_rejects_unknown_provider(tmp_path: Path) -> None:
    cfg = load_config(tmp_path / "config.toml")
    cfg.vision.provider = "unknown"
    with pytest.raises(ValueError, match="Unsupported vision.provider"):
        build_extractor(cfg)



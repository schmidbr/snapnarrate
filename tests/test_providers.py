from __future__ import annotations

import copy
import json

import pytest

from snap_narrate.config import AppConfig
from snap_narrate.providers import build_vision, prompts, register_vision, vision_names
from snap_narrate.providers.base import ExtractResult
from snap_narrate.providers.elevenlabs import ElevenLabsSpeech
from snap_narrate.providers.ollama import OllamaVision
from snap_narrate.providers.openai import OpenAIVision


class Resp:
    def __init__(self, payload: object = None, status: int = 200, content: bytes = b"") -> None:
        self.status_code = status
        self._payload = payload
        self.content = content
        self.text = json.dumps(payload) if payload is not None else ""

    def json(self) -> object:
        return self._payload


class FakeSession:
    def __init__(self, responses: list[Resp]) -> None:
        self.responses = responses
        self.requests: list[dict] = []

    def post(self, url: str, **kwargs) -> Resp:  # noqa: ANN003
        self.requests.append(copy.deepcopy({"url": url, **kwargs}))  # snapshot: callers may reuse the payload
        return self.responses.pop(0)

    get = post


# ---- parsing ----------------------------------------------------------------------------


def test_parse_extraction_handles_wrapped_json_and_string_bools() -> None:
    result = prompts.parse_extraction('Sure!\n```json\n{"text": " Hi ", "confidence": "0.8", "more_text_likely": "yes"}\n```')
    assert result == ExtractResult(text="Hi", confidence=0.8, dropped_reason=None, more_text_likely=True)


def test_parse_extraction_reports_bad_payloads() -> None:
    assert prompts.parse_extraction("").dropped_reason == "empty_response"
    assert prompts.parse_extraction("no json here").dropped_reason == "malformed_json"


def test_parse_paragraphs_sorts_and_dedupes() -> None:
    raw = json.dumps({"paragraphs": [{"index": 2, "text": "B"}, {"index": 1, "text": "A"}, {"index": 3, "text": "a"}], "dropped_reason": None})
    items, dropped = prompts.parse_paragraphs(raw)
    assert [p["text"] for p in items] == ["A", "B"]
    assert dropped is None


# ---- OpenAI -----------------------------------------------------------------------------


def test_openai_sends_image_and_parses_reply() -> None:
    reply = {"choices": [{"message": {"content": json.dumps({"text": "Lore", "confidence": 0.9})}}], "usage": {"total_tokens": 5}}
    session = FakeSession([Resp(reply)])
    vision = OpenAIVision("key", "gpt-test", session=session, ultra_fast_model="gpt-fast")
    assert vision.extract(b"\xff\xd8\xffjpeg").text == "Lore"
    body = session.requests[0]["json"]
    assert body["model"] == "gpt-test"
    assert body["messages"][1]["content"][1]["image_url"]["url"].startswith("data:image/jpeg;base64,")

    session.responses.append(Resp(reply))
    vision.extract_first(b"png")
    assert session.requests[1]["json"]["model"] == "gpt-fast"


def test_openai_requires_key() -> None:
    with pytest.raises(ValueError):
        OpenAIVision("", "m", session=FakeSession([])).extract(b"x")


# ---- Ollama -----------------------------------------------------------------------------


def _ollama(responses: list[dict], fast_mode: bool = False) -> tuple[OllamaVision, FakeSession]:
    session = FakeSession([Resp(r) for r in responses])
    return OllamaVision("http://ollama", "llava", fast_mode=fast_mode, session=session), session


def _paragraphs(*texts: str) -> dict:
    return {"response": json.dumps({"paragraphs": [{"index": i, "text": t, "confidence": 0.9} for i, t in enumerate(texts)], "dropped_reason": None})}


def test_ollama_retries_low_coverage_then_finalizes() -> None:
    vision, session = _ollama([_paragraphs("P1"), _paragraphs("P1", "P2"), {"response": json.dumps({"text": "P1\n\nP2", "confidence": 0.95, "dropped_reason": None})}])
    assert vision.extract(b"img").text == "P1\n\nP2"
    assert len(session.requests) == 3


def test_ollama_falls_back_to_joined_paragraphs() -> None:
    vision, _ = _ollama([_paragraphs("Para A", "Para B"), {"response": ""}])
    result = vision.extract(b"img")
    assert result.text == "Para A\n\nPara B" and result.dropped_reason == "pass2_fallback_join"


def test_ollama_fast_mode_is_one_call() -> None:
    vision, session = _ollama([_paragraphs("P1", "P2")], fast_mode=True)
    assert vision.extract(b"img").text == "P1\n\nP2"
    assert len(session.requests) == 1


# ---- ElevenLabs -------------------------------------------------------------------------


def test_elevenlabs_uses_fast_model_only_for_first_chunk() -> None:
    session = FakeSession([Resp(content=b"a"), Resp(content=b"b")])
    speech = ElevenLabsSpeech("k", "voice", "hq-model", "fast-model", "pcm_24000", session=session)
    speech.synthesize("one", fast=True)
    speech.synthesize("two")
    assert [r["json"]["model_id"] for r in session.requests] == ["fast-model", "hq-model"]
    assert session.requests[0]["params"] == {"output_format": "pcm_24000"}


def test_elevenlabs_missing_voice_is_a_config_error() -> None:
    with pytest.raises(ValueError):
        ElevenLabsSpeech("k", "").synthesize("hi")


# ---- registry ---------------------------------------------------------------------------


def test_addons_can_register_vision_providers() -> None:
    marker = object()
    register_vision("unit-test-ocr", lambda cfg: marker)  # type: ignore[arg-type,return-value]
    cfg = AppConfig()
    cfg.vision.provider = "unit-test-ocr"
    assert "unit-test-ocr" in vision_names()
    assert build_vision(cfg) is marker


# ---- Ollama Cloud -----------------------------------------------------------------------


def test_ollama_cloud_sends_key_and_disables_thinking() -> None:
    cfg = AppConfig()
    cfg.vision.provider = "ollama-cloud"
    cfg.ollama_cloud.api_key = "oc-key"
    vision = build_vision(cfg)
    assert isinstance(vision, OllamaVision)
    assert vision.base_url == "https://ollama.com" and vision.model == "gemma4:31b"

    session = FakeSession([Resp(_paragraphs("P1", "P2"))])
    vision._session = session
    vision.fast_mode = True
    vision.extract(b"img")
    request = session.requests[0]
    assert request["url"] == "https://ollama.com/api/generate"
    assert request["headers"] == {"Authorization": "Bearer oc-key"}
    assert request["json"]["think"] is False


def test_local_ollama_sends_no_auth_header() -> None:
    vision, session = _ollama([_paragraphs("P1", "P2")], fast_mode=True)
    vision.extract(b"img")
    assert session.requests[0]["headers"] == {}


def test_ollama_retries_without_think_when_model_rejects_it() -> None:
    rejected = Resp({"error": "model does not support thinking"}, status=400)
    session = FakeSession([rejected, Resp(_paragraphs("P1", "P2"))])
    vision = OllamaVision("http://ollama", "llava", fast_mode=True, session=session)
    assert vision.extract(b"img").text == "P1\n\nP2"
    assert "think" in session.requests[0]["json"] and "think" not in session.requests[1]["json"]


def test_ollama_cloud_bad_key_is_a_config_error() -> None:
    session = FakeSession([Resp({"error": "unauthorized"}, status=401)])
    vision = OllamaVision("https://ollama.com", "gemma4:31b", api_key="bad", session=session)
    with pytest.raises(ValueError, match="API key"):
        vision.extract_first(b"img")

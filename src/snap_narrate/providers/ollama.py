"""Ollama vision provider: a local Ollama server, or metered Ollama Cloud (https://ollama.com).

Smaller local models tend to stop after one paragraph, so full extraction is two passes:
collect paragraphs as structured JSON (retrying once in strict mode if coverage is low),
then ask the model to assemble them into the final text.
"""

from __future__ import annotations

import base64
import logging
from typing import Any

from snap_narrate.providers import prompts
from snap_narrate.providers.base import ExtractResult
from snap_narrate.providers.net import Session

logger = logging.getLogger("snap_narrate")

_EXTRACT_SCHEMA = {
    "type": "object",
    "properties": {
        "text": {"type": "string"},
        "confidence": {"type": "number"},
        "dropped_reason": {"type": ["string", "null"]},
    },
    "required": ["text", "confidence", "dropped_reason"],
}
_FIRST_SCHEMA = {
    "type": "object",
    "properties": {**_EXTRACT_SCHEMA["properties"], "more_text_likely": {"type": "boolean"}},
    "required": [*_EXTRACT_SCHEMA["required"], "more_text_likely"],
}
_PARAGRAPHS_SCHEMA = {
    "type": "object",
    "properties": {
        "paragraphs": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "index": {"type": "integer"},
                    "text": {"type": "string"},
                    "confidence": {"type": "number"},
                },
                "required": ["index", "text", "confidence"],
            },
        },
        "dropped_reason": {"type": ["string", "null"]},
    },
    "required": ["paragraphs", "dropped_reason"],
}


class OllamaVision:
    def __init__(
        self,
        base_url: str,
        model: str,
        ignore_short_lines: int = 4,
        timeout_sec: int = 60,
        keep_alive: str = "5m",
        num_predict: int = 2048,
        temperature: float = 0.1,
        top_p: float = 0.9,
        min_paragraphs: int = 2,
        coverage_retry_attempts: int = 1,
        fast_mode: bool = True,
        ultra_fast_mode: bool = True,
        ultra_fast_model: str = "",
        api_key: str = "",
        session: Any = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key.strip()  # only needed for Ollama Cloud
        self.model = model
        self.ignore_short_lines = ignore_short_lines
        self.timeout_sec = timeout_sec
        self.keep_alive = keep_alive
        self.options = {"num_predict": num_predict, "temperature": temperature, "top_p": top_p}
        self.min_paragraphs = min_paragraphs
        self.coverage_retry_attempts = coverage_retry_attempts
        self.fast_mode = fast_mode
        self.ultra_fast_mode = ultra_fast_mode
        self.ultra_fast_model = ultra_fast_model.strip()
        self._session = session or Session()

    def extract(self, image: bytes, profile: str = "default") -> ExtractResult:
        image_b64 = base64.b64encode(image).decode("ascii")
        items, dropped = self._collect(image_b64, profile, strict=False)
        retried = False

        if self.fast_mode:
            result = prompts.join_paragraphs(items, "fast_mode_join" if items else (dropped or ""))
        else:
            if len(items) < self.min_paragraphs and self.coverage_retry_attempts > 0:
                retried = True
                retry_items, retry_dropped = self._collect(image_b64, profile, strict=True)
                if len(retry_items) > len(items):
                    items, dropped = retry_items, retry_dropped
            if not items:
                result = ExtractResult(text="", dropped_reason=dropped or "empty_response")
            else:
                result = self._finalize(items, profile)
                if not result.text:
                    result = prompts.join_paragraphs(items, "pass2_fallback_join")

        logger.info(
            "event=extract_result provider=ollama chars=%s paragraphs=%s retried=%s dropped_reason=%s",
            len(result.text),
            len(items),
            retried,
            result.dropped_reason,
        )
        return result

    def extract_first(self, image: bytes, profile: str = "default") -> ExtractResult:
        prompt = prompts.first_paragraph_prompt(self.ignore_short_lines, profile, ultra_fast_mode=self.ultra_fast_mode)
        model = self.ultra_fast_model or self.model
        raw = self._generate(prompt, _FIRST_SCHEMA, model=model, image_b64=base64.b64encode(image).decode("ascii"))
        result = self._parse_with_fallback(raw)
        logger.info(
            "event=initial_extract_result provider=ollama chars=%s more_text_likely=%s model=%s",
            len(result.text),
            result.more_text_likely,
            model,
        )
        return result

    def list_models(self) -> list[str]:
        response = self._session.get(f"{self.base_url}/api/tags", headers=self._headers(), timeout=10)
        response.raise_for_status()
        return [str(m.get("name", "")) for m in response.json().get("models", [])]

    def _collect(self, image_b64: str, profile: str, strict: bool) -> tuple[list[dict[str, Any]], str | None]:
        prompt = prompts.paragraph_collection_prompt(self.ignore_short_lines, profile, strict=strict)
        raw = self._generate(prompt, _PARAGRAPHS_SCHEMA, model=self.model, image_b64=image_b64)
        items, dropped = prompts.parse_paragraphs(raw)
        if not items and dropped in {"malformed_json", "empty_response"}:
            logger.warning("event=ollama_paragraph_parse_warning dropped_reason=%s preview=%r", dropped, raw[:180])
        return items, dropped

    def _finalize(self, items: list[dict[str, Any]], profile: str) -> ExtractResult:
        raw = self._generate(prompts.paragraph_finalize_prompt(items, profile), _EXTRACT_SCHEMA, model=self.model)
        return self._parse_with_fallback(raw)

    @staticmethod
    def _parse_with_fallback(raw: str) -> ExtractResult:
        result = prompts.parse_extraction(raw)
        if result.dropped_reason == "malformed_json" and raw.strip():
            # Some local models ignore the schema and answer in plain text.
            return ExtractResult(text=raw.strip(), confidence=0.35, dropped_reason="non_json_fallback")
        return result

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}

    def _post_generate(self, payload: dict[str, Any]) -> Any:
        return self._session.post(
            f"{self.base_url}/api/generate", json=payload, headers=self._headers(), timeout=self.timeout_sec
        )

    def _generate(self, prompt: str, schema: dict[str, Any], model: str, image_b64: str | None = None) -> str:
        payload: dict[str, Any] = {
            "model": model,
            "prompt": prompt + " Output JSON only, no markdown.",
            "stream": False,
            "format": schema,
            "keep_alive": self.keep_alive,
            "options": self.options,
            # Reading text needs no reasoning; thinking only adds latency (and billed tokens on cloud).
            "think": False,
        }
        if image_b64 is not None:
            payload["images"] = [image_b64]
        response = self._post_generate(payload)
        if response.status_code >= 400 and "think" in response.text.lower():
            # Some models reject the think option outright; retry without it.
            payload.pop("think")
            response = self._post_generate(payload)
        if response.status_code in (401, 403):
            raise ValueError("Ollama Cloud rejected the API key. Check it in Settings.")
        if response.status_code >= 400:
            raise RuntimeError(f"Ollama extraction failed ({response.status_code}): {response.text[:200]}")
        data = response.json()
        logger.info(
            "event=ollama_usage model=%s prompt_tokens=%s output_tokens=%s",
            model,
            data.get("prompt_eval_count"),
            data.get("eval_count"),
        )
        if isinstance(data.get("response"), str):
            return data["response"]
        message = data.get("message")
        if isinstance(message, dict) and isinstance(message.get("content"), str):
            return message["content"]
        return ""

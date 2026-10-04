"""OpenAI (or any OpenAI-compatible /v1/chat/completions endpoint) vision provider."""

from __future__ import annotations

import base64
import logging
from typing import Any

from snap_narrate.providers import prompts
from snap_narrate.providers.base import ExtractResult
from snap_narrate.providers.net import Session
from snap_narrate.usage import record_openai_usage

logger = logging.getLogger("snap_narrate")


def image_media_type(image: bytes) -> str:
    return "image/jpeg" if image.startswith(b"\xff\xd8\xff") else "image/png"


class OpenAIVision:
    def __init__(
        self,
        api_key: str,
        model: str,
        ignore_short_lines: int = 4,
        timeout_sec: int = 60,
        base_url: str = "https://api.openai.com",
        fast_mode: bool = True,
        ultra_fast_mode: bool = True,
        ultra_fast_model: str = "",
        session: Any = None,
    ) -> None:
        self.api_key = api_key
        self.model = model
        self.ignore_short_lines = ignore_short_lines
        self.timeout_sec = timeout_sec
        self.base_url = base_url.rstrip("/")
        self.fast_mode = fast_mode
        self.ultra_fast_mode = ultra_fast_mode
        self.ultra_fast_model = ultra_fast_model.strip()
        self._session = session or Session()

    def extract(self, image: bytes, profile: str = "default") -> ExtractResult:
        prompt = prompts.full_prompt(self.ignore_short_lines, profile, fast_mode=self.fast_mode)
        return self._request(image, prompt, self.model, "extract_result")

    def extract_first(self, image: bytes, profile: str = "default") -> ExtractResult:
        prompt = prompts.first_paragraph_prompt(self.ignore_short_lines, profile, ultra_fast_mode=self.ultra_fast_mode)
        return self._request(image, prompt, self.ultra_fast_model or self.model, "initial_extract_result")

    def _request(self, image: bytes, prompt: str, model: str, log_event: str) -> ExtractResult:
        if not self.api_key:
            raise ValueError("OpenAI API key is missing. Open Settings to add it.")

        data_url = f"data:{image_media_type(image)};base64,{base64.b64encode(image).decode('ascii')}"
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": "You output strict JSON only."},
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {"type": "image_url", "image_url": {"url": data_url}},
                    ],
                },
            ],
            "temperature": 0,
            "response_format": {"type": "json_object"},
        }
        response = self._session.post(
            f"{self.base_url}/v1/chat/completions",
            headers={"Authorization": f"Bearer {self.api_key}"},
            json=payload,
            timeout=self.timeout_sec,
        )
        if response.status_code >= 400:
            raise RuntimeError(f"OpenAI extraction failed ({response.status_code}): {response.text[:200]}")

        data = response.json()
        if isinstance(data.get("usage"), dict):
            record_openai_usage(data["usage"])
        result = prompts.parse_extraction(data["choices"][0]["message"]["content"] or "")
        logger.info(
            "event=%s chars=%s confidence=%.2f dropped_reason=%s more_text_likely=%s model=%s",
            log_event,
            len(result.text),
            result.confidence,
            result.dropped_reason,
            result.more_text_likely,
            model,
        )
        return result

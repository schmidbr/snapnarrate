from __future__ import annotations

import json
import logging
import re
from typing import Any

from screen_reader.models import ExtractResult


def parse_extraction_payload(raw_content: str) -> ExtractResult:
    content = raw_content.strip()
    if not content:
        return ExtractResult(text="", confidence=0.0, dropped_reason="empty_response")

    try:
        parsed = json.loads(content)
    except json.JSONDecodeError:
        match = re.search(r"\{[\s\S]*\}", content)
        if not match:
            return ExtractResult(text="", confidence=0.0, dropped_reason="malformed_json")
        try:
            parsed = json.loads(match.group(0))
        except json.JSONDecodeError:
            return ExtractResult(text="", confidence=0.0, dropped_reason="malformed_json")

    text = str(parsed.get("text", "")).strip()
    confidence = parsed.get("confidence", 0.0)
    dropped_reason = parsed.get("dropped_reason")

    try:
        confidence_val = float(confidence)
    except (TypeError, ValueError):
        confidence_val = 0.0

    if dropped_reason is not None:
        dropped_reason = str(dropped_reason)

    return ExtractResult(text=text, confidence=confidence_val, dropped_reason=dropped_reason)


class OpenAIVisionExtractor:
    def __init__(
        self,
        api_key: str,
        model: str,
        ignore_short_lines: int,
        timeout_sec: int = 60,
        base_url: str = "https://api.openai.com",
    ) -> None:
        self.api_key = api_key
        self.model = model
        self.ignore_short_lines = ignore_short_lines
        self.timeout_sec = timeout_sec
        self.base_url = base_url.rstrip("/")

    def extract_narrative_text(self, image_bytes: bytes, game_profile: str = "default") -> ExtractResult:
        import base64

        import requests

        if not self.api_key:
            raise ValueError("OpenAI API key is missing")

        prompt = build_extraction_prompt(self.ignore_short_lines, game_profile)

        image_b64 = base64.b64encode(image_bytes).decode("ascii")

        payload: dict[str, Any] = {
            "model": self.model,
            "messages": [
                {
                    "role": "system",
                    "content": "You output strict JSON only.",
                },
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt + f" Profile: {game_profile}."},
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:image/png;base64,{image_b64}"},
                        },
                    ],
                },
            ],
            "temperature": 0,
            "response_format": {"type": "json_object"},
        }

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        response = requests.post(
            f"{self.base_url}/v1/chat/completions",
            headers=headers,
            json=payload,
            timeout=self.timeout_sec,
        )
        if response.status_code >= 400:
            raise RuntimeError(f"OpenAI extraction failed ({response.status_code}): {response.text[:200]}")

        data = response.json()
        raw_content = data["choices"][0]["message"]["content"]
        result = parse_extraction_payload(raw_content)
        logging.getLogger("screen_reader").info(
            "event=extract_result chars=%s confidence=%.2f dropped_reason=%s",
            len(result.text),
            result.confidence,
            result.dropped_reason,
        )
        return result


def build_extraction_prompt(ignore_short_lines: int, game_profile: str) -> str:
    return (
        "You are a strict OCR filter for games. Read the screenshot and return only long-form narrative text "
        "(dialogue, lore, quest narrative, books/journals). Exclude menus, HUD labels, minimap text, button "
        "hints, health/ammo counters, and short subtitles. Keep verbatim wording. "
        "Return all visible narrative paragraphs in reading order and preserve paragraph breaks. "
        "Do not stop after the first paragraph."
        f" Ignore lines with fewer than {ignore_short_lines} words unless they are part of a larger paragraph. "
        "Return JSON exactly with keys: text (string), confidence (number 0-1), dropped_reason (string or null). "
        f"Profile: {game_profile}."
    )


def build_paragraph_collection_prompt(ignore_short_lines: int, game_profile: str, strict: bool = False) -> str:
    strict_suffix = (
        " Include every visible narrative paragraph from top-to-bottom with no omissions."
        if strict
        else ""
    )
    return (
        "Extract narrative paragraphs from this game screenshot. Return only long-form story/dialog/lore paragraphs, "
        "ordered top-to-bottom and left-to-right in the main content column. Exclude menus, HUD, sidebars, buttons, "
        "toolbars, notifications, and unrelated UI clutter. Keep verbatim text and preserve paragraph boundaries."
        f" Ignore lines with fewer than {ignore_short_lines} words unless they belong to a paragraph."
        " Output JSON with keys: paragraphs (array of objects with index, text, confidence), dropped_reason (string or null)."
        f"{strict_suffix} Profile: {game_profile}."
    )


def parse_paragraph_collection_payload(raw_content: str) -> tuple[list[dict[str, Any]], str | None]:
    content = raw_content.strip()
    if not content:
        return [], "empty_response"

    try:
        parsed = json.loads(content)
    except json.JSONDecodeError:
        match = re.search(r"\{[\s\S]*\}", content)
        if not match:
            return [], "malformed_json"
        try:
            parsed = json.loads(match.group(0))
        except json.JSONDecodeError:
            return [], "malformed_json"

    paragraphs = parsed.get("paragraphs", [])
    dropped_reason = parsed.get("dropped_reason")
    if dropped_reason is not None:
        dropped_reason = str(dropped_reason)

    if not isinstance(paragraphs, list):
        return [], dropped_reason or "invalid_paragraphs"

    out: list[dict[str, Any]] = []
    for i, item in enumerate(paragraphs):
        if not isinstance(item, dict):
            continue
        text = str(item.get("text", "")).strip()
        if not text:
            continue
        try:
            index = int(item.get("index", i))
        except (TypeError, ValueError):
            index = i
        try:
            confidence = float(item.get("confidence", 0.0))
        except (TypeError, ValueError):
            confidence = 0.0
        out.append({"index": index, "text": text, "confidence": confidence})

    return out, dropped_reason


def normalize_paragraphs(paragraphs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    ordered = sorted(paragraphs, key=lambda p: int(p.get("index", 0)))
    normalized: list[dict[str, Any]] = []
    for p in ordered:
        text = re.sub(r"\s+", " ", str(p.get("text", "")).strip())
        if not text:
            continue
        key = text.lower()
        if key in seen:
            continue
        seen.add(key)
        normalized.append({"index": p.get("index", 0), "text": text, "confidence": p.get("confidence", 0.0)})
    return normalized


def build_paragraph_finalize_prompt(paragraphs: list[dict[str, Any]], game_profile: str) -> str:
    paragraph_lines = []
    for p in paragraphs:
        paragraph_lines.append(f"[{p['index']}] {p['text']}")
    blob = "\n".join(paragraph_lines)
    return (
        "Given these extracted narrative paragraphs, produce final narration output as strict JSON with keys "
        "text, confidence, dropped_reason. text must include all paragraphs in order, separated by blank lines. "
        "Do not summarize or omit content."
        f" Profile: {game_profile}.\nParagraphs:\n{blob}"
    )


def merge_text_blocks(base_text: str, continuation_text: str) -> str:
    base = base_text.rstrip()
    cont = continuation_text.lstrip()
    if not base:
        return cont
    if not cont:
        return base

    max_overlap = min(len(base), len(cont), 500)
    overlap = 0
    for size in range(max_overlap, 20, -1):
        if base[-size:].lower() == cont[:size].lower():
            overlap = size
            break

    suffix = cont[overlap:].lstrip()
    joiner = "" if base.endswith(("\n", " ")) or suffix.startswith(("\n", " ")) else "\n\n"
    return (base + joiner + suffix).strip()


def is_likely_truncated(raw_content: str, parsed_result: ExtractResult, response_data: dict[str, Any]) -> bool:
    done_reason = str(response_data.get("done_reason", "")).lower()
    if done_reason in {"length", "max_tokens"}:
        return True

    done_flag = response_data.get("done")
    if done_flag is False:
        return True

    text = (parsed_result.text or raw_content).strip()
    if not text:
        return False

    if text.endswith(("...", "…", ",", ";", ":", "-", "—", "(")):
        return True

    if text.count("{") != text.count("}"):
        return True

    if len(text) >= 200 and not text.endswith((".", "!", "?", "\"", "'")):
        return True

    return False


class OllamaVisionExtractor:
    def __init__(
        self,
        base_url: str,
        model: str,
        ignore_short_lines: int,
        timeout_sec: int = 60,
        keep_alive: str = "5m",
        num_predict: int = 2048,
        temperature: float = 0.1,
        top_p: float = 0.9,
        continuation_attempts: int = 1,
        min_paragraphs: int = 2,
        coverage_retry_attempts: int = 1,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.ignore_short_lines = ignore_short_lines
        self.timeout_sec = timeout_sec
        self.keep_alive = keep_alive
        self.num_predict = num_predict
        self.temperature = temperature
        self.top_p = top_p
        self.continuation_attempts = continuation_attempts
        self.min_paragraphs = min_paragraphs
        self.coverage_retry_attempts = coverage_retry_attempts

    def extract_narrative_text(self, image_bytes: bytes, game_profile: str = "default") -> ExtractResult:
        import base64

        import requests

        image_b64 = base64.b64encode(image_bytes).decode("ascii")
        retry_used = 0
        paragraphs, dropped_reason = self._collect_paragraphs(
            requests_module=requests,
            image_b64=image_b64,
            game_profile=game_profile,
            strict=False,
        )
        paragraphs = normalize_paragraphs(paragraphs)
        if len(paragraphs) < self.min_paragraphs and self.coverage_retry_attempts > 0:
            retry_used = 1
            retry_paragraphs, retry_dropped = self._collect_paragraphs(
                requests_module=requests,
                image_b64=image_b64,
                game_profile=game_profile,
                strict=True,
            )
            retry_paragraphs = normalize_paragraphs(retry_paragraphs)
            if len(retry_paragraphs) > len(paragraphs):
                paragraphs = retry_paragraphs
                dropped_reason = retry_dropped

        coverage_low = len(paragraphs) < self.min_paragraphs

        if not paragraphs:
            result = ExtractResult(text="", confidence=0.0, dropped_reason=dropped_reason or "empty_response")
        else:
            result = self._finalize_paragraphs(
                requests_module=requests,
                paragraphs=paragraphs,
                game_profile=game_profile,
            )
            if not result.text:
                joined = "\n\n".join(p["text"] for p in paragraphs)
                avg_conf = sum(float(p["confidence"]) for p in paragraphs) / max(len(paragraphs), 1)
                result = ExtractResult(text=joined, confidence=avg_conf, dropped_reason="pass2_fallback_join")

        final_chars = len(result.text)
        logging.getLogger("screen_reader").info(
            "event=extract_result provider=ollama chars=%s confidence=%.2f dropped_reason=%s paragraph_count=%s retry_used=%s coverage_low=%s final_chars=%s",
            len(result.text),
            result.confidence,
            result.dropped_reason,
            len(paragraphs),
            retry_used,
            coverage_low,
            final_chars,
        )
        return result

    def _generate(self, payload: dict[str, Any], requests_module: Any) -> dict[str, Any]:
        response = requests_module.post(
            f"{self.base_url}/api/generate",
            json=payload,
            timeout=self.timeout_sec,
        )
        if response.status_code >= 400:
            raise RuntimeError(f"Ollama extraction failed ({response.status_code}): {response.text[:200]}")
        return response.json()

    @staticmethod
    def _extract_ollama_content(data: dict[str, Any]) -> str:
        response_text = data.get("response")
        if isinstance(response_text, str):
            return response_text

        message = data.get("message")
        if isinstance(message, dict):
            content = message.get("content")
            if isinstance(content, str):
                return content

        return ""

    @staticmethod
    def _parse_ollama_response(data: dict[str, Any], raw_content: str) -> ExtractResult:
        result = parse_extraction_payload(raw_content)
        if result.dropped_reason == "malformed_json":
            # Fallback path: non-ideal outputs sometimes provide plain text directly.
            plain = raw_content.strip()
            if plain:
                return ExtractResult(text=plain, confidence=0.35, dropped_reason="non_json_fallback")
        return result

    def _collect_paragraphs(
        self,
        requests_module: Any,
        image_b64: str,
        game_profile: str,
        strict: bool,
    ) -> tuple[list[dict[str, Any]], str | None]:
        prompt = build_paragraph_collection_prompt(self.ignore_short_lines, game_profile, strict=strict)
        payload: dict[str, Any] = {
            "model": self.model,
            "prompt": prompt + " Output JSON only, no markdown.",
            "images": [image_b64],
            "stream": False,
            "format": {
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
            },
            "keep_alive": self.keep_alive,
            "options": {
                "num_predict": self.num_predict,
                "temperature": self.temperature,
                "top_p": self.top_p,
            },
        }
        data = self._generate(payload, requests_module)
        raw_content = self._extract_ollama_content(data)
        paragraphs, dropped_reason = parse_paragraph_collection_payload(raw_content)
        if not paragraphs and dropped_reason in {"malformed_json", "empty_response"}:
            logging.getLogger("screen_reader").warning(
                "event=ollama_paragraph_parse_warning dropped_reason=%s response_keys=%s raw_preview=%s",
                dropped_reason,
                sorted(data.keys()),
                raw_content[:180].replace("\n", " "),
            )
        return paragraphs, dropped_reason

    def _finalize_paragraphs(
        self,
        requests_module: Any,
        paragraphs: list[dict[str, Any]],
        game_profile: str,
    ) -> ExtractResult:
        prompt = build_paragraph_finalize_prompt(paragraphs, game_profile)
        payload: dict[str, Any] = {
            "model": self.model,
            "prompt": prompt + " Output JSON only, no markdown.",
            "stream": False,
            "format": {
                "type": "object",
                "properties": {
                    "text": {"type": "string"},
                    "confidence": {"type": "number"},
                    "dropped_reason": {"type": ["string", "null"]},
                },
                "required": ["text", "confidence", "dropped_reason"],
            },
            "keep_alive": self.keep_alive,
            "options": {
                "num_predict": self.num_predict,
                "temperature": self.temperature,
                "top_p": self.top_p,
            },
        }
        data = self._generate(payload, requests_module)
        raw_content = self._extract_ollama_content(data)
        result = self._parse_ollama_response(data, raw_content)
        return result

    def _continuation_payload(self, image_b64: str, game_profile: str, previous_text: str) -> dict[str, Any]:
        continuation_prompt = (
            build_extraction_prompt(self.ignore_short_lines, game_profile)
            + " You previously returned a partial extraction. Continue from where you stopped and return ONLY "
            + "the missing tail text as JSON with the same schema."
            + f" Already extracted text starts with: {previous_text[:500]}"
        )
        return {
            "model": self.model,
            "prompt": continuation_prompt,
            "images": [image_b64],
            "stream": False,
            "format": {
                "type": "object",
                "properties": {
                    "text": {"type": "string"},
                    "confidence": {"type": "number"},
                    "dropped_reason": {"type": ["string", "null"]},
                },
                "required": ["text", "confidence", "dropped_reason"],
            },
            "keep_alive": self.keep_alive,
            "options": {
                "num_predict": self.num_predict,
                "temperature": self.temperature,
                "top_p": self.top_p,
            },
        }

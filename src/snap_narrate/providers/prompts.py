"""Prompts shared by vision providers and parsing of their JSON replies."""

from __future__ import annotations

import json
import re
from typing import Any

from snap_narrate.providers.base import ExtractResult

_EXCLUDE = (
    "Exclude menus, HUD labels, minimap text, button hints, health/ammo counters, notifications, "
    "and short subtitles. Keep verbatim wording."
)


def full_prompt(ignore_short_lines: int, profile: str, fast_mode: bool = False) -> str:
    speed = (
        " Prioritize speed over completeness: return the main visible narrative block first."
        if fast_mode
        else ""
    )
    return (
        "You are a strict OCR filter for games. Read the screenshot and return only long-form narrative text "
        f"(dialogue, lore, quest narrative, books/journals). {_EXCLUDE} "
        "Return all visible narrative paragraphs in reading order, separated by newlines. "
        f"Ignore lines with fewer than {ignore_short_lines} words unless they are part of a larger paragraph.{speed} "
        "Return JSON with keys: text (string), confidence (number 0-1), dropped_reason (string or null). "
        f"Game profile: {profile}."
    )


def first_paragraph_prompt(ignore_short_lines: int, profile: str, ultra_fast_mode: bool = True) -> str:
    speed = " Return quickly, even if more text exists below it." if ultra_fast_mode else ""
    return (
        "You are a strict OCR filter for games. Read the screenshot and return only the FIRST long-form narrative "
        f"paragraph (dialogue, lore, quest narrative, books/journals). {_EXCLUDE} "
        f"Ignore lines with fewer than {ignore_short_lines} words unless they are part of that paragraph.{speed} "
        "Return JSON with keys: text (string), confidence (number 0-1), dropped_reason (string or null), "
        "more_text_likely (boolean: true when more narrative remains after the returned paragraph). "
        f"Game profile: {profile}."
    )


def paragraph_collection_prompt(ignore_short_lines: int, profile: str, strict: bool = False) -> str:
    strict_suffix = " Include every visible narrative paragraph from top to bottom with no omissions." if strict else ""
    return (
        "Extract narrative paragraphs from this game screenshot. Return only long-form story/dialog/lore paragraphs, "
        "ordered top-to-bottom and left-to-right in the main content column. Exclude menus, HUD, sidebars, buttons, "
        "toolbars, notifications, and unrelated UI clutter. Keep verbatim text and paragraph boundaries."
        f" Ignore lines with fewer than {ignore_short_lines} words unless they belong to a paragraph."
        " Output JSON with keys: paragraphs (array of objects with index, text, confidence), dropped_reason (string or null)."
        f"{strict_suffix} Game profile: {profile}."
    )


def paragraph_finalize_prompt(items: list[dict[str, Any]], profile: str) -> str:
    blob = "\n".join(f"[{p['index']}] {p['text']}" for p in items)
    return (
        "Given these extracted narrative paragraphs, produce final narration output as strict JSON with keys "
        "text, confidence, dropped_reason. text must include all paragraphs in order, separated by blank lines. "
        f"Do not summarize or omit content. Game profile: {profile}.\nParagraphs:\n{blob}"
    )


def _load_json_object(raw: str) -> dict[str, Any] | None:
    content = raw.strip()
    if not content:
        return None
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError:
        # Models sometimes wrap JSON in prose or code fences.
        match = re.search(r"\{[\s\S]*\}", content)
        if not match:
            return None
        try:
            parsed = json.loads(match.group(0))
        except json.JSONDecodeError:
            return None
    return parsed if isinstance(parsed, dict) else None


def _as_bool(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"true", "yes", "1"}:
            return True
        if lowered in {"false", "no", "0"}:
            return False
    return None


def _as_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def parse_extraction(raw: str) -> ExtractResult:
    if not raw.strip():
        return ExtractResult(text="", dropped_reason="empty_response")
    parsed = _load_json_object(raw)
    if parsed is None:
        return ExtractResult(text="", dropped_reason="malformed_json")
    dropped = parsed.get("dropped_reason")
    return ExtractResult(
        text=str(parsed.get("text", "") or "").strip(),
        confidence=_as_float(parsed.get("confidence", 0.0)),
        dropped_reason=None if dropped is None else str(dropped),
        more_text_likely=_as_bool(parsed.get("more_text_likely")),
    )


def parse_paragraphs(raw: str) -> tuple[list[dict[str, Any]], str | None]:
    if not raw.strip():
        return [], "empty_response"
    parsed = _load_json_object(raw)
    if parsed is None:
        return [], "malformed_json"

    dropped = parsed.get("dropped_reason")
    dropped_reason = None if dropped is None else str(dropped)
    items = parsed.get("paragraphs", [])
    if not isinstance(items, list):
        return [], dropped_reason or "invalid_paragraphs"

    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for position, item in enumerate(items):
        if not isinstance(item, dict):
            continue
        text = re.sub(r"\s+", " ", str(item.get("text", "") or "")).strip()
        if not text or text.lower() in seen:
            continue
        seen.add(text.lower())
        try:
            index = int(item.get("index", position))
        except (TypeError, ValueError):
            index = position
        out.append({"index": index, "text": text, "confidence": _as_float(item.get("confidence", 0.0))})
    out.sort(key=lambda p: p["index"])
    return out, dropped_reason


def join_paragraphs(items: list[dict[str, Any]], dropped_reason: str) -> ExtractResult:
    if not items:
        return ExtractResult(text="", dropped_reason=dropped_reason or "empty_response")
    return ExtractResult(
        text="\n\n".join(p["text"] for p in items),
        confidence=sum(p["confidence"] for p in items) / len(items),
        dropped_reason=dropped_reason,
    )

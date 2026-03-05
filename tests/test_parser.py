from __future__ import annotations

from snap_narrate.models import ExtractResult
from snap_narrate.openai_client import (
    build_extraction_prompt,
    build_paragraph_collection_prompt,
    is_likely_truncated,
    merge_text_blocks,
    parse_paragraph_collection_payload,
    parse_extraction_payload,
)


def test_parse_extraction_payload_json() -> None:
    result = parse_extraction_payload('{"text":"Hello there","confidence":0.88,"dropped_reason":null}')
    assert result.text == "Hello there"
    assert result.confidence == 0.88
    assert result.dropped_reason is None


def test_parse_extraction_payload_noisy_wrapper() -> None:
    raw = "Model output:\n```json\n{\"text\":\"Story block\",\"confidence\":0.72,\"dropped_reason\":null}\n```"
    result = parse_extraction_payload(raw)
    assert result.text == "Story block"
    assert result.confidence == 0.72


def test_parse_extraction_payload_malformed() -> None:
    result = parse_extraction_payload("not-json-at-all")
    assert result.text == ""
    assert result.dropped_reason == "malformed_json"


def test_prompt_requires_all_paragraphs() -> None:
    prompt = build_extraction_prompt(4, "default")
    assert "Return all visible narrative paragraphs" in prompt
    assert "Do not stop after the first paragraph" in prompt


def test_truncation_detection_by_done_reason() -> None:
    result = ExtractResult(text="Some text", confidence=0.8, dropped_reason=None)
    assert is_likely_truncated("{}", result, {"done_reason": "length"}) is True


def test_merge_text_blocks_avoids_overlap_duplication() -> None:
    base = "First paragraph.\n\nSecond paragraph starts here and continues"
    continuation = "Second paragraph starts here and continues to the end."
    merged = merge_text_blocks(base, continuation)
    assert merged.count("Second paragraph starts here") == 1


def test_parse_paragraph_collection_payload_valid() -> None:
    raw = (
        '{"paragraphs":[{"index":0,"text":"P1","confidence":0.9},{"index":1,"text":"P2","confidence":0.8}],'
        '"dropped_reason":null}'
    )
    paragraphs, dropped = parse_paragraph_collection_payload(raw)
    assert len(paragraphs) == 2
    assert paragraphs[0]["text"] == "P1"
    assert dropped is None


def test_paragraph_collection_prompt_requires_ordering() -> None:
    prompt = build_paragraph_collection_prompt(4, "default", strict=True)
    assert "ordered top-to-bottom and left-to-right" in prompt
    assert "Include every visible narrative paragraph" in prompt


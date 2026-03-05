from __future__ import annotations

import json

from snap_narrate.openai_client import OllamaVisionExtractor


class FakeOllamaExtractor(OllamaVisionExtractor):
    def __init__(self, responses: list[dict[str, str]]) -> None:
        super().__init__(
            base_url="http://localhost:11434",
            model="fake",
            ignore_short_lines=4,
            timeout_sec=60,
            keep_alive="5m",
            num_predict=2048,
            temperature=0.1,
            top_p=0.9,
            continuation_attempts=1,
            min_paragraphs=2,
            coverage_retry_attempts=1,
        )
        self._responses = responses
        self.calls = 0

    def _generate(self, payload: dict[str, object], requests_module: object) -> dict[str, object]:  # type: ignore[override]
        self.calls += 1
        return self._responses.pop(0)


def test_ollama_two_pass_retry_for_low_coverage() -> None:
    responses = [
        {"response": json.dumps({"paragraphs": [{"index": 0, "text": "P1", "confidence": 0.9}], "dropped_reason": None})},
        {
            "response": json.dumps(
                {
                    "paragraphs": [
                        {"index": 0, "text": "P1", "confidence": 0.9},
                        {"index": 1, "text": "P2", "confidence": 0.9},
                    ],
                    "dropped_reason": None,
                }
            )
        },
        {"response": json.dumps({"text": "P1\n\nP2", "confidence": 0.95, "dropped_reason": None})},
    ]
    extractor = FakeOllamaExtractor(responses)
    result = extractor.extract_narrative_text(b"img", "default")
    assert "P1" in result.text
    assert "P2" in result.text
    assert extractor.calls == 3


def test_ollama_finalize_fallback_joins_paragraphs_when_pass2_empty() -> None:
    responses = [
        {
            "response": json.dumps(
                {
                    "paragraphs": [
                        {"index": 0, "text": "Para A", "confidence": 0.8},
                        {"index": 1, "text": "Para B", "confidence": 0.8},
                    ],
                    "dropped_reason": None,
                }
            )
        },
        {"response": ""},
    ]
    extractor = FakeOllamaExtractor(responses)
    result = extractor.extract_narrative_text(b"img", "default")
    assert "Para A" in result.text
    assert "Para B" in result.text


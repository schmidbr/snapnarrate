"""Provider contracts. Anything that satisfies these protocols can be plugged in."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass
class ExtractResult:
    text: str
    confidence: float = 0.0
    dropped_reason: str | None = None
    # Set by the quick first pass: does more narrative likely follow what was returned?
    more_text_likely: bool | None = None


class VisionProvider(Protocol):
    """Reads narrative text out of a screenshot."""

    def extract(self, image: bytes, profile: str = "default") -> ExtractResult:
        """Full extraction: every narrative paragraph, in reading order."""
        ...

    def extract_first(self, image: bytes, profile: str = "default") -> ExtractResult:
        """Quick pass: just the first paragraph, plus a more_text_likely hint."""
        ...


class SpeechProvider(Protocol):
    """Turns text into encoded audio in `output_format` (e.g. "mp3_44100_128", "pcm_24000")."""

    output_format: str

    def synthesize(self, text: str, fast: bool = False) -> bytes:
        """`fast` asks for the lowest-latency model; used for the first spoken chunk."""
        ...

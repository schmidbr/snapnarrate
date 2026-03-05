from __future__ import annotations

import hashlib
import re
from difflib import SequenceMatcher


def normalize_text(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = [re.sub(r"\s+", " ", line).strip() for line in text.split("\n")]
    lines = [line for line in lines if line]
    return "\n".join(lines).strip()


class TextDeduper:
    def __init__(self, similarity_threshold: float = 0.95) -> None:
        self.similarity_threshold = similarity_threshold
        self._last_text = ""
        self._last_hash = ""

    def seen_recently(self, text: str) -> bool:
        normalized = normalize_text(text)
        text_hash = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
        if not self._last_hash:
            self._last_hash = text_hash
            self._last_text = normalized
            return False

        if text_hash == self._last_hash:
            return True

        similarity = SequenceMatcher(None, normalized, self._last_text).ratio()
        if similarity >= self.similarity_threshold:
            self._last_hash = text_hash
            self._last_text = normalized
            return True

        self._last_hash = text_hash
        self._last_text = normalized
        return False

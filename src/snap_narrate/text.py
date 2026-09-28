"""Pure text helpers: normalization, dedup, and the chunking/alignment used by speech-first playback."""

from __future__ import annotations

import hashlib
import re
from difflib import SequenceMatcher

_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")
_SENTENCE_END = (".", "!", "?", '"', "'")


def normalize_text(text: str) -> str:
    """Collapse whitespace within lines and drop blank lines. Paragraphs stay newline-separated."""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = [re.sub(r"\s+", " ", line).strip() for line in text.split("\n")]
    return "\n".join(line for line in lines if line)


def paragraphs(text: str) -> list[str]:
    return [part.strip() for part in text.split("\n") if part.strip()]


class TextDeduper:
    """Remembers the last narrated text and flags near-identical repeats."""

    def __init__(self, similarity_threshold: float = 0.95) -> None:
        self.similarity_threshold = similarity_threshold
        self._last_text = ""
        self._last_hash = ""

    def seen_recently(self, text: str) -> bool:
        normalized = normalize_text(text)
        text_hash = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
        previous_hash, previous_text = self._last_hash, self._last_text
        self._last_hash, self._last_text = text_hash, normalized
        if not previous_hash:
            return False
        if text_hash == previous_hash:
            return True
        return SequenceMatcher(None, normalized, previous_text).ratio() >= self.similarity_threshold


def head_chunk(text: str, max_chars: int) -> str:
    """The first speakable piece of text: the first paragraph, trimmed to whole sentences
    within max_chars where possible, else to a word boundary."""
    parts = paragraphs(normalize_text(text))
    if not parts:
        return ""
    first = parts[0]
    if len(first) <= max_chars:
        return first

    out: list[str] = []
    for sentence in (s.strip() for s in _SENTENCE_SPLIT.split(first) if s.strip()):
        candidate = " ".join(out + [sentence])
        if out and len(candidate) > max_chars:
            break
        out.append(sentence)
        if len(candidate) >= max_chars:
            break
    # A single sentence may overrun a little (cutting mid-sentence sounds worse), but not
    # unboundedly: text without punctuation would otherwise become one huge "fast" chunk.
    if out and len(" ".join(out)) <= max_chars * 2:
        return " ".join(out)

    truncated = first[:max_chars].rsplit(" ", 1)[0].strip()
    return truncated or first[:max_chars].strip()


def adaptive_initial_chars(text: str, more_text_likely: bool | None, base_chars: int) -> int:
    """Pick the first-chunk size: whole block if it is short and complete, smaller when a
    long passage follows so speech starts sooner."""
    normalized = normalize_text(text)
    if not normalized:
        return base_chars

    parts = paragraphs(normalized)
    first_len = len(parts[0]) if parts else 0
    total = len(normalized)

    if more_text_likely is False and total <= max(base_chars + 80, 320):
        return max(base_chars, total)

    chars = base_chars
    if more_text_likely is True:
        chars = min(chars, 190)
    if total >= 520 or first_len >= 420:
        chars = min(chars, 140)
    elif more_text_likely is True and (total >= 360 or first_len >= 280):
        chars = min(chars, 150)
    elif total >= 360 or first_len >= 280:
        chars = min(chars, 170)
    return max(110, chars)


def should_continue(more_text_likely: bool | None, spoken: str, initial_chars: int) -> bool:
    """After speaking the first chunk, is a full extraction worth it?"""
    if more_text_likely is not None:
        return more_text_likely
    normalized = normalize_text(spoken)
    if not normalized:
        return False
    if len(normalized) >= max(initial_chars - 24, 80):
        return True
    return not normalized.endswith(_SENTENCE_END)


def remaining_after(full_text: str, spoken_text: str) -> str:
    """The part of full_text not yet covered by spoken_text.

    The quick first pass and the full pass can phrase the opening slightly differently, so
    this tries an exact prefix, a near-start substring, a suffix/prefix overlap, then a
    fuzzy prefix match. Returns "" when the two cannot be aligned (never replays the start).
    """
    full = normalize_text(full_text)
    spoken = normalize_text(spoken_text)
    if not full or not spoken:
        return full

    full_lower, spoken_lower = full.lower(), spoken.lower()
    if full_lower.startswith(spoken_lower):
        return full[len(spoken) :].strip()

    idx = full_lower.find(spoken_lower)
    if 0 <= idx <= 24:
        return full[idx + len(spoken) :].strip()

    for size in range(min(len(full), len(spoken), 500), 20, -1):
        if spoken_lower[-size:] == full_lower[:size]:
            return full[size:].strip()

    fuzzy = _fuzzy_remaining(full, spoken)
    return fuzzy if fuzzy is not None else ""


def _fuzzy_remaining(full: str, spoken: str) -> str | None:
    min_prefix = max(40, int(len(spoken) * 0.55))
    search_limit = min(len(full), max(len(spoken) + 220, int(len(spoken) * 1.5)))
    window = full[:search_limit]

    candidates: set[int] = {min(len(full), len(spoken)), search_limit}
    candidates.update(m.start() for m in re.finditer(r"(?<=[.!?])(?:\s+|$)", window))
    for idx in range(min_prefix, search_limit + 1, 24):
        candidates.add(idx)
        boundary = window.rfind(" ", 0, idx + 1)
        if boundary > 0:
            candidates.add(boundary)

    spoken_lower = spoken.lower()
    best_end, best_score = -1, 0.0
    for end in sorted(candidates):
        if end < min_prefix or end > len(full):
            continue
        prefix = full[:end].strip()
        if not prefix:
            continue
        ratio = SequenceMatcher(None, spoken_lower, prefix.lower()).ratio()
        score = ratio - (abs(len(prefix) - len(spoken)) / max(len(spoken), 1)) * 0.08
        if score > best_score:
            best_end, best_score = end, score

    if best_end < 0 or best_score < 0.72:
        return None
    remaining = full[best_end:].strip()
    if remaining.startswith((",", ";", ":", ")", "]")):
        remaining = remaining[1:].lstrip()
    return remaining


def followup_chunks(text: str, chunk_chars: int, min_chars: int) -> list[str]:
    """Split the remaining text into TTS-sized chunks along paragraph and sentence lines,
    dropping fragments shorter than min_chars."""
    chunks: list[str] = []
    for paragraph in paragraphs(text):
        remaining = paragraph
        while remaining:
            if len(remaining) <= chunk_chars:
                if len(remaining) >= min_chars:
                    chunks.append(remaining)
                break
            head = head_chunk(remaining, chunk_chars)
            if not head or head == remaining:
                if len(remaining) >= min_chars:
                    chunks.append(remaining)
                break
            if len(head) >= min_chars:
                chunks.append(head)
            remaining = remaining[len(head) :].strip()
    return chunks

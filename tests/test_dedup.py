from __future__ import annotations

from snap_narrate.text_processing import TextDeduper


def test_deduper_exact_duplicate() -> None:
    deduper = TextDeduper(0.95)
    assert deduper.seen_recently("Long story paragraph") is False
    assert deduper.seen_recently("Long story paragraph") is True


def test_deduper_similarity_duplicate() -> None:
    deduper = TextDeduper(0.90)
    first = "This is a long narrative block with many words and details for testing"
    second = "This is a long narrative block with many words plus details for testing"
    assert deduper.seen_recently(first) is False
    assert deduper.seen_recently(second) is True


def test_deduper_new_text() -> None:
    deduper = TextDeduper(0.98)
    assert deduper.seen_recently("Narrative one with text") is False
    assert deduper.seen_recently("Completely different lore entry") is False


from snap_narrate.text import (
    TextDeduper,
    adaptive_initial_chars,
    followup_chunks,
    head_chunk,
    normalize_text,
    remaining_after,
    should_continue,
)


def test_normalize_collapses_whitespace_and_blank_lines() -> None:
    assert normalize_text("  Hello   world \r\n\r\n  Second\tline ") == "Hello world\nSecond line"


def test_deduper_flags_exact_and_near_repeats() -> None:
    dedup = TextDeduper(0.9)
    text = "The quick brown fox jumps over the lazy dog near the river bank."
    assert dedup.seen_recently(text) is False
    assert dedup.seen_recently(text) is True
    assert dedup.seen_recently(text.replace("river", "rivers")) is True
    assert dedup.seen_recently("Completely different narrative about a haunted lighthouse.") is False


def test_head_chunk_prefers_whole_sentences() -> None:
    text = "First sentence here. Second sentence follows. Third one is long enough to overflow the limit."
    assert head_chunk(text, 45) == "First sentence here. Second sentence follows."


def test_head_chunk_falls_back_to_word_boundary() -> None:
    assert head_chunk("word " * 40, 22) == "word word word word"


def test_adaptive_chunk_keeps_short_complete_block_whole() -> None:
    text = "A short complete paragraph that should be spoken as one block without being shortened."
    chars = adaptive_initial_chars(text, more_text_likely=False, base_chars=180)
    assert chars >= len(text)
    assert head_chunk(text, chars) == text


def test_adaptive_chunk_shrinks_for_long_continuing_block() -> None:
    text = "Sentence number one is here. " * 25
    assert adaptive_initial_chars(text, more_text_likely=True, base_chars=220) == 140


def test_should_continue_trusts_model_hint_then_heuristics() -> None:
    assert should_continue(True, "Done.", 220) is True
    assert should_continue(False, "x" * 400, 220) is False
    assert should_continue(None, "A short complete thought.", 220) is False
    assert should_continue(None, "An unfinished thought that trails", 220) is True


def test_remaining_after_exact_prefix() -> None:
    assert remaining_after("Alpha beta.\nGamma delta.", "Alpha beta.") == "Gamma delta."


def test_remaining_after_fuzzy_prefix_does_not_replay_opening() -> None:
    spoken = "The ancient door creaked open, revealing a hall lit by a single guttering torch."
    full = (
        "The ancient door creaked open revealing a hall lit by one guttering torch.\n"
        "Beyond it, the stairs descended into a darkness that seemed to breathe."
    )
    assert remaining_after(full, spoken).startswith("Beyond it")


def test_remaining_after_unalignable_returns_empty() -> None:
    assert remaining_after("Totally unrelated text about ships and harbors at dawn.", "Nothing in common with the other passage here.") == ""


def test_followup_chunks_split_and_drop_tiny_tails() -> None:
    para = "One two three four five. " * 20
    chunks = followup_chunks(para + "\nok", chunk_chars=120, min_chars=20)
    assert all(len(c) <= 125 for c in chunks)
    assert "ok" not in chunks
    assert " ".join(chunks).count("One") == 20

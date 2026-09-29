from __future__ import annotations

import time
from pathlib import Path

from snap_narrate import events
from snap_narrate.events import EventBus
from snap_narrate.history import History, format_when


def narrate(bus: EventBus, session: int, source: str, text: str, status: str = "played", final_after: str = "") -> None:
    """Publish the events a narration produces. final_after simulates the full passage
    arriving after speech started (the speech-first path)."""
    bus.publish(events.NARRATION_STARTED, session=session, source=source)
    bus.publish(events.NARRATION_TEXT, session=session, text=text, final=not final_after)
    bus.publish(events.NARRATION_FINISHED, session=session, source=source, status=status)
    if final_after:
        bus.publish(events.NARRATION_TEXT, session=session, text=final_after, final=True)


def recorder(tmp_path: Path, **kwargs) -> tuple[History, EventBus]:  # noqa: ANN003
    history = History(tmp_path / "history.json", **kwargs)
    history.run_id = "run1"
    bus = EventBus()
    history.attach(bus)
    return history, bus


def test_records_played_narrations_newest_first(tmp_path: Path) -> None:
    history, bus = recorder(tmp_path)
    narrate(bus, 1, "hotkey:fullscreen", "First passage.")
    narrate(bus, 2, "tray:region", "Second passage.")
    entries = history.entries()
    assert [e.text for e in entries] == ["Second passage.", "First passage."]
    assert entries[0].trigger == "Region" and entries[0].run_id == "run1" and entries[0].session == 2


def test_full_passage_replaces_first_chunk_text(tmp_path: Path) -> None:
    history, bus = recorder(tmp_path)
    narrate(bus, 1, "hotkey:fullscreen", "Opening line.", final_after="Opening line. And the rest of the passage.")
    assert history.latest().text == "Opening line. And the rest of the passage."


def test_skips_failures_diagnostics_and_replays(tmp_path: Path) -> None:
    history, bus = recorder(tmp_path)
    narrate(bus, 1, "hotkey:fullscreen", "Skipped text", status="skipped")
    narrate(bus, 2, "self_test", "Self test")
    narrate(bus, 3, "test_voice", "Voice test")
    narrate(bus, 4, "replay", "Replayed")
    assert history.entries() == []


def test_disabled_history_records_nothing(tmp_path: Path) -> None:
    history, bus = recorder(tmp_path, enabled=False)
    narrate(bus, 1, "hotkey:fullscreen", "Private text")
    assert history.entries() == []


def test_capped_persisted_and_editable(tmp_path: Path) -> None:
    history, bus = recorder(tmp_path, max_items=3)
    for session in range(1, 6):
        narrate(bus, session, "api", f"Passage {session}")
    assert [e.text for e in history.entries()] == ["Passage 5", "Passage 4", "Passage 3"]

    reloaded = History(tmp_path / "history.json")
    assert [e.text for e in reloaded.entries()] == ["Passage 5", "Passage 4", "Passage 3"]

    version = reloaded.version
    reloaded.delete(reloaded.latest().id)
    assert reloaded.version > version and len(reloaded.entries()) == 2
    reloaded.clear()
    assert History(tmp_path / "history.json").entries() == []


def test_corrupt_file_is_ignored(tmp_path: Path) -> None:
    (tmp_path / "history.json").write_text("{not json", encoding="utf-8")
    assert History(tmp_path / "history.json").entries() == []


def test_format_when() -> None:
    now = time.mktime((2026, 9, 28, 19, 30, 0, 0, 0, -1))
    assert format_when(now - 3600, now) == "Today 6:30 PM"
    assert format_when(now - 86400, now) == "Yesterday 7:30 PM"
    assert format_when(now - 7 * 86400, now) == "Sep 21 7:30 PM"

import pytest

from snap_narrate import events
from snap_narrate.events import Event
from snap_narrate.progress import PENDING_TAIL, ProgressTracker


def plan(session: int, chars: list[int], final: bool) -> Event:
    return Event(events.NARRATION_PLAN, {"session": session, "chunk_chars": chars, "final": final})


def chunk(session: int, index: int, chars: int, duration: float) -> Event:
    return Event(events.SPEECH_CHUNK, {"session": session, "index": index, "text": "x" * chars, "duration": duration})


def progress(session: int, index: int, position: float, duration: float) -> Event:
    return Event(events.SPEECH_PROGRESS, {"session": session, "index": index, "position": position, "duration": duration})


def test_open_plan_reserves_a_pending_tail() -> None:
    tracker = ProgressTracker()
    tracker.handle(plan(1, [150], final=False))
    state = tracker.state()
    assert len(state.segments) == 1
    assert state.pending_from == pytest.approx(1 - PENDING_TAIL)
    assert state.segments[0].estimated and state.segments[0].fill == 0


def test_current_segment_fills_from_real_position_and_upcoming_are_estimated() -> None:
    tracker = ProgressTracker(chars_per_sec=15)
    tracker.handle(plan(1, [150, 300], final=True))
    tracker.handle(chunk(1, 0, 150, duration=10.0))  # measured exactly 15 chars/s
    tracker.handle(progress(1, 0, 5.0, 10.0))
    first, second = tracker.state().segments
    assert first.fill == pytest.approx(0.5) and not first.estimated
    assert second.estimated and second.fill == 0
    # 10 s played-duration vs 300 chars / 15 cps = 20 s estimate -> one third / two thirds
    assert first.end == pytest.approx(1 / 3)
    assert tracker.state().pending_from is None


def test_finished_segments_are_full_and_plan_growth_keeps_them() -> None:
    tracker = ProgressTracker()
    tracker.handle(plan(1, [100], final=False))
    tracker.handle(chunk(1, 0, 100, duration=6.0))
    tracker.handle(plan(1, [100, 200, 200], final=True))
    tracker.handle(chunk(1, 1, 200, duration=12.0))
    segments = tracker.state().segments
    assert [s.fill for s in segments] == [1.0, 0.0, 0.0]
    assert [s.estimated for s in segments] == [False, False, True]


def test_speaking_rate_is_learned_and_survives_new_sessions() -> None:
    tracker = ProgressTracker(chars_per_sec=15)
    tracker.handle(chunk(1, 0, 200, duration=10.0))  # 20 chars/s
    assert tracker.chars_per_sec > 15
    learned = tracker.chars_per_sec
    tracker.handle(plan(2, [80], final=True))
    assert tracker.session == 2 and tracker.chars_per_sec == learned
    assert len(tracker.state().segments) == 1


def test_stale_session_progress_is_ignored() -> None:
    tracker = ProgressTracker()
    tracker.handle(plan(2, [100], final=True))
    assert tracker.handle(progress(1, 0, 3.0, 5.0)) is False
    assert tracker.state().segments[0].fill == 0

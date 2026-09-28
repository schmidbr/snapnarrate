import pytest

from snap_narrate.hotkeys import MOD_ALT, MOD_CONTROL, MOD_SHIFT, MOD_WIN, parse_hotkey


@pytest.mark.parametrize(
    ("spec", "expected"),
    [
        ("ctrl+shift+n", (MOD_CONTROL | MOD_SHIFT, ord("N"))),
        ("Alt + F9", (MOD_ALT, 0x78)),
        ("win+5", (MOD_WIN, ord("5"))),
        ("ctrl+space", (MOD_CONTROL, 0x20)),
        ("ctrl+num7", (MOD_CONTROL, 0x67)),
        ("pause", (0, 0x13)),
    ],
)
def test_parse_hotkey(spec: str, expected: tuple[int, int]) -> None:
    assert parse_hotkey(spec) == expected


@pytest.mark.parametrize("spec", ["", "ctrl+shift", "ctrl+a+b", "ctrl+banana", "f25"])
def test_parse_hotkey_rejects_invalid(spec: str) -> None:
    with pytest.raises(ValueError):
        parse_hotkey(spec)


def test_recording_uses_virtual_key_codes() -> None:
    from snap_narrate.hotkeys import spec_from_keys

    assert spec_from_keys({"shift", "ctrl"}, 0x4E) == "ctrl+shift+n"  # modifier order is canonical
    assert spec_from_keys(set(), 0x78) == "f9"
    assert spec_from_keys({"alt"}, 0x31) == "alt+1"  # Shift+1 is still "1", not "!"
    assert spec_from_keys({"ctrl"}, 0x67) == "ctrl+num7"
    assert spec_from_keys({"ctrl"}, 0xFF) is None  # a key hotkeys can't use


def test_recorded_specs_round_trip_through_the_parser() -> None:
    from snap_narrate.hotkeys import spec_from_keys

    for vk in [*range(0x41, 0x5B), *range(0x30, 0x3A), *range(0x70, 0x88), *range(0x60, 0x6A), 0x20, 0x21, 0xBE]:
        spec = spec_from_keys({"ctrl"}, vk)
        assert spec is not None and parse_hotkey(spec)[1] == vk


def test_keycaps_for_display() -> None:
    from snap_narrate.hotkeys import keycaps

    assert keycaps("ctrl+shift+n") == ["Ctrl", "Shift", "N"]
    assert keycaps("alt+pageup") == ["Alt", "Page Up"]
    assert keycaps("f10") == ["F10"]


def test_hotkey_problems_explained() -> None:
    from snap_narrate.ui.widgets import hotkey_problem

    assert hotkey_problem("ctrl+shift+n", []) is None
    assert hotkey_problem("f9", []) is None  # lone function keys are fine for games
    assert "Ctrl" in hotkey_problem("n", [])
    assert "Already used" in hotkey_problem("ctrl+shift+n", ["ctrl+shift+n"])
    assert hotkey_problem("ctrl+banana", []) is not None

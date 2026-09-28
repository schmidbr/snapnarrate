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

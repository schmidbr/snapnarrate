from __future__ import annotations

import pytest


def test_picker_left_alone_closes_its_overlay() -> None:
    from snap_narrate.ui.region import select_region
    from snap_narrate.ui.tk_thread import TkThread

    ui = TkThread()
    if ui.root is None:
        pytest.skip("Tk unavailable")
    try:
        assert select_region(ui, timeout=0.2) is None
        assert ui.call(lambda: [w for w in ui.root.winfo_children() if w.winfo_exists()], timeout=2) == []
    finally:
        ui.stop()

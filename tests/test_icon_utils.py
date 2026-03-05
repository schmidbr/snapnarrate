from __future__ import annotations

from snap_narrate.icon_utils import icon_asset_path, load_tray_icon


def test_icon_asset_path_points_to_ico() -> None:
    assert icon_asset_path().name == "snapnarrate.ico"


def test_load_tray_icon_returns_image() -> None:
    image = load_tray_icon()
    assert image.size[0] > 0
    assert image.size[1] > 0


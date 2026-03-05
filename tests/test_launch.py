from __future__ import annotations

from pathlib import Path

from snap_narrate.launch import appdata_config_path, resolve_default_config_path


def test_appdata_config_path_ends_with_snapnarrate_config() -> None:
    path = appdata_config_path()
    assert path.name == "config.toml"
    assert "SnapNarrate" in str(path)


def test_resolve_default_config_prefers_existing_file(tmp_path: Path, monkeypatch) -> None:
    exe_path = tmp_path / "snapnarrate.exe"
    exe_path.write_text("x", encoding="utf-8")
    config = tmp_path / "config.toml"
    config.write_text("x", encoding="utf-8")
    monkeypatch.setattr("snap_narrate.launch.executable_target", lambda: exe_path)
    path = resolve_default_config_path()
    assert path == config


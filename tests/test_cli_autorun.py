from __future__ import annotations

from pathlib import Path

from snap_narrate import cli


def test_main_no_args_autoruns(monkeypatch, tmp_path: Path) -> None:
    config_path = tmp_path / "config.toml"
    captured: dict[str, object] = {}

    monkeypatch.setattr("snap_narrate.cli.resolve_default_config_path", lambda: config_path)

    def fake_init_config(path: Path, force: bool = False) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("", encoding="utf-8")
        return path

    monkeypatch.setattr("snap_narrate.cli.init_config", fake_init_config)

    def fake_run_command(config_path: Path, game_profile: str, auto_launch: bool = False) -> int:
        captured["config_path"] = config_path
        captured["game_profile"] = game_profile
        captured["auto_launch"] = auto_launch
        return 0

    monkeypatch.setattr("snap_narrate.cli.run_command", fake_run_command)
    result = cli.main([])
    assert result == 0
    assert captured["config_path"] == config_path
    assert captured["game_profile"] == "default"
    assert captured["auto_launch"] is True


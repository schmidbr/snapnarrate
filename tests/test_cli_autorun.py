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


def test_run_command_builds_startup_manager_with_explicit_launch_args(tmp_path: Path, monkeypatch) -> None:
    captured: dict[str, object] = {}
    config_path = tmp_path / "config.toml"
    config_path.write_text("", encoding="utf-8")

    def fake_launch_command(path: Path, include_args: bool = True) -> tuple[str, str, str]:
        captured["config_path"] = path
        captured["include_args"] = include_args
        return ("python.exe", "launch args", str(tmp_path))

    class FakeScreenCapturer:
        def __init__(self, **kwargs) -> None:  # noqa: ANN003
            captured["capturer_kwargs"] = kwargs

    class FakeTTS:
        def __init__(self, **kwargs) -> None:  # noqa: ANN003
            captured["tts_kwargs"] = kwargs

    class FakePlayer:
        pass

    class FakePipeline:
        def __init__(self, **kwargs) -> None:  # noqa: ANN003
            captured["pipeline_kwargs"] = kwargs

    class FakeRuntime:
        def __init__(self, *args, startup_manager, **kwargs) -> None:  # noqa: ANN002,ANN003
            captured["startup_args"] = startup_manager.arguments
            captured["startup_target"] = startup_manager.target
            captured["runtime_kwargs"] = kwargs

        def start(self) -> None:
            captured["started"] = True

    monkeypatch.setattr("snap_narrate.cli.launch_command", fake_launch_command)
    monkeypatch.setattr("snap_narrate.cli.build_extractor", lambda cfg: object())
    monkeypatch.setattr("snap_narrate.cli.setup_logging", lambda path: Path(path))
    monkeypatch.setattr("snap_narrate.cli.icon_asset_path", lambda: tmp_path / "missing.ico")
    monkeypatch.setattr("snap_narrate.cli.UsageService.from_config", lambda cfg: object())
    monkeypatch.setattr("snap_narrate.capture.ScreenCapturer", FakeScreenCapturer)
    monkeypatch.setattr("snap_narrate.elevenlabs_client.ElevenLabsClient", FakeTTS)
    monkeypatch.setattr("snap_narrate.elevenlabs_client.TempFileAudioPlayer", FakePlayer)
    monkeypatch.setattr("snap_narrate.pipeline.NarrationPipeline", FakePipeline)
    monkeypatch.setattr("snap_narrate.runtime.SnapNarrateRuntime", FakeRuntime)

    result = cli.run_command(config_path, game_profile="default", auto_launch=False)

    assert result == 0
    assert captured["config_path"] == config_path
    assert captured["include_args"] is True
    assert captured["startup_args"] == "launch args"
    assert captured["capturer_kwargs"] == {
        "cooldown_ms": 1500,
        "save_debug": False,
        "debug_dir": "debug_screenshots",
        "max_dimension": 1600,
        "image_format": "jpeg",
        "jpeg_quality": 85,
    }
    assert captured["tts_kwargs"]["speech_fast_model_id"] == ""
    assert captured["pipeline_kwargs"]["speech_first_enabled"] is True
    assert captured["pipeline_kwargs"]["initial_chunk_chars"] == 220
    assert captured["pipeline_kwargs"]["followup_chunk_chars"] == 650
    assert captured["pipeline_kwargs"]["followup_min_chars"] == 60
    assert captured["runtime_kwargs"]["capture_sound_name"] == "Windows Balloon"
    assert captured["started"] is True


def test_self_test_command_runs_fixture_pipeline(tmp_path: Path, monkeypatch, capsys) -> None:
    captured: dict[str, object] = {}

    class FakePipeline:
        def process_self_test(self, image_bytes: bytes, game_profile: str = "self-test"):  # noqa: ANN001
            captured["image_bytes"] = image_bytes
            captured["game_profile"] = game_profile
            from snap_narrate.models import PipelineResult, PipelineTimings

            return PipelineResult(
                status="played",
                message="Narration played",
                chars=88,
                timings=PipelineTimings(extract_ms=11, tts_ms=22, playback_ms=3, total_ms=36),
            )

    class FakeCapturer:
        max_dimension = 900
        image_format = "jpeg"
        jpeg_quality = 80

    monkeypatch.setattr(
        "snap_narrate.cli.build_runtime_parts",
        lambda config_path: {"capturer": FakeCapturer(), "pipeline": FakePipeline(), "log_path": tmp_path / "test.log"},
    )
    monkeypatch.setattr("snap_narrate.cli.setup_logging", lambda path: Path(path))
    monkeypatch.setattr("snap_narrate.cli.create_self_test_image_bytes", lambda **kwargs: b"fixture-bytes")

    result = cli.self_test_command(tmp_path / "config.toml", "default")
    output = capsys.readouterr().out

    assert result == 0
    assert captured["image_bytes"] == b"fixture-bytes"
    assert captured["game_profile"] == "default-self-test"
    assert "Self-test status: played" in output

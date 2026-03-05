from __future__ import annotations

import argparse
import ctypes
import json
import sys
import time
from pathlib import Path

from snap_narrate.config import DEFAULT_CONFIG_PATH, init_config, load_config
from snap_narrate.extractor_factory import build_extractor
from snap_narrate.icon_utils import icon_asset_path
from snap_narrate.launch import launch_command, resolve_default_config_path
from snap_narrate.logging_utils import setup_logging
from snap_narrate.shortcuts import ShortcutManager
from snap_narrate.startup import StartupManager
from snap_narrate.ui import launch_settings_ui_with_startup
from snap_narrate.usage import UsageService


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="snapnarrate", description="SnapNarrate game narrator")
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="Run the hotkey + tray narrator")
    run.add_argument("--config", type=Path, default=DEFAULT_CONFIG_PATH)
    run.add_argument("--game-profile", default="default")

    doctor = sub.add_parser("doctor", help="Validate local setup")
    doctor.add_argument("--config", type=Path, default=DEFAULT_CONFIG_PATH)

    voices = sub.add_parser("voices", help="List TTS voices")
    voices.add_argument("--config", type=Path, default=DEFAULT_CONFIG_PATH)
    voices.add_argument("--provider", choices=["elevenlabs"], default="elevenlabs")

    test_capture = sub.add_parser("test-capture", help="Take one screenshot and print extraction output")
    test_capture.add_argument("--config", type=Path, default=DEFAULT_CONFIG_PATH)
    test_capture.add_argument("--game-profile", default="default")

    ui = sub.add_parser("ui", help="Open desktop settings UI")
    ui.add_argument("--config", type=Path, default=DEFAULT_CONFIG_PATH)

    install_shortcut = sub.add_parser("install-shortcut", help="Create desktop shortcut")
    install_shortcut.add_argument("--config", type=Path, default=DEFAULT_CONFIG_PATH)

    startup = sub.add_parser("startup", help="Manage run-at-startup")
    startup.add_argument("--config", type=Path, default=DEFAULT_CONFIG_PATH)
    startup_group = startup.add_mutually_exclusive_group()
    startup_group.add_argument("--enable", action="store_true")
    startup_group.add_argument("--disable", action="store_true")
    startup_group.add_argument("--status", action="store_true")

    usage = sub.add_parser("usage", help="Show OpenAI and ElevenLabs usage/credits")
    usage.add_argument("--config", type=Path, default=DEFAULT_CONFIG_PATH)
    usage.add_argument("--json", action="store_true", dest="as_json")

    cfg = sub.add_parser("config", help="Config helpers")
    cfg_sub = cfg.add_subparsers(dest="config_command", required=True)
    cfg_init = cfg_sub.add_parser("init", help="Create config.toml")
    cfg_init.add_argument("--config", type=Path, default=DEFAULT_CONFIG_PATH)
    cfg_init.add_argument("--force", action="store_true")

    return parser


def _required_settings_missing(cfg: object) -> bool:
    from snap_narrate.config import AppConfig

    if not isinstance(cfg, AppConfig):
        return True
    if not cfg.elevenlabs.api_key or not cfg.elevenlabs.voice_id:
        return True
    if cfg.vision.provider == "openai":
        return not (cfg.openai.api_key and cfg.openai.model)
    if cfg.vision.provider == "ollama":
        return not (cfg.ollama.base_url and cfg.ollama.model)
    return True


def run_command(config_path: Path, game_profile: str, auto_launch: bool = False) -> int:
    from snap_narrate.capture import ScreenCapturer
    from snap_narrate.elevenlabs_client import ElevenLabsClient, TempFileAudioPlayer
    from snap_narrate.pipeline import NarrationPipeline
    from snap_narrate.runtime import SnapNarrateRuntime

    def build_runtime_parts(config_file: Path) -> dict[str, object]:
        cfg = load_config(config_file)
        extractor = build_extractor(cfg)
        tts = ElevenLabsClient(
            api_key=cfg.elevenlabs.api_key,
            voice_id=cfg.elevenlabs.voice_id,
            model_id=cfg.elevenlabs.model_id,
            output_format=cfg.elevenlabs.output_format,
        )
        player = TempFileAudioPlayer()
        pipeline = NarrationPipeline(
            extractor=extractor,
            tts=tts,
            player=player,
            min_block_chars=cfg.filter.min_block_chars,
            dedup_enabled=cfg.dedup.enabled,
            dedup_similarity_threshold=cfg.dedup.similarity_threshold,
            retry_count=cfg.playback.retry_count,
            retry_backoff_ms=cfg.playback.retry_backoff_ms,
        )
        capturer = ScreenCapturer(
            cooldown_ms=cfg.capture.cooldown_ms,
            save_debug=cfg.debug.save_screenshots,
            debug_dir=cfg.debug.screenshot_dir,
        )
        return {
            "capturer": capturer,
            "pipeline": pipeline,
            "hotkey": cfg.capture.hotkey,
            "stop_hotkey": cfg.capture.stop_hotkey,
            "log_path": Path(cfg.log_file),
            "usage_service": UsageService.from_config(cfg),
        }

    target, args, workdir = launch_command(config_path, include_args=False)
    icon_path = str(icon_asset_path()) if icon_asset_path().exists() else None
    startup_manager = StartupManager(ShortcutManager(), target=target, arguments=args, working_dir=workdir, icon_path=icon_path)

    cfg_for_bootstrap = load_config(config_path)
    if auto_launch and _required_settings_missing(cfg_for_bootstrap):
        launch_settings_ui_with_startup(config_path, startup_manager)
        cfg_for_bootstrap = load_config(config_path)
        if _required_settings_missing(cfg_for_bootstrap):
            print("Setup incomplete. Configure required settings to start.")
            return 1

    parts = build_runtime_parts(config_path)
    log_path = setup_logging(str(parts["log_path"]))
    startup_notice = "SnapNarrate is running in tray." if auto_launch else None
    if auto_launch and cfg_for_bootstrap.vision.provider == "ollama":
        startup_notice = "SnapNarrate is running. If extraction fails, open tray > Settings."
    runtime = SnapNarrateRuntime(
        capturer=parts["capturer"],  # type: ignore[arg-type]
        pipeline=parts["pipeline"],  # type: ignore[arg-type]
        hotkey=str(parts["hotkey"]),
        stop_hotkey=str(parts["stop_hotkey"]),
        log_path=log_path,
        game_profile=game_profile,
        config_path=config_path,
        reload_callback=build_runtime_parts,
        startup_manager=startup_manager,
        usage_service=parts.get("usage_service"),  # type: ignore[arg-type]
        startup_notice=startup_notice,
    )
    runtime.start()
    return 0


def doctor_command(config_path: Path) -> int:
    import requests

    cfg = load_config(config_path)

    checks: list[tuple[str, bool, str, bool]] = []
    checks.append(("Config file exists", config_path.exists(), str(config_path), True))
    checks.append(("Vision provider", cfg.vision.provider in {"openai", "ollama"}, cfg.vision.provider, True))
    checks.append(("Vision timeout_sec", cfg.vision.timeout_sec > 0, str(cfg.vision.timeout_sec), True))
    if cfg.vision.provider == "openai":
        checks.append(("OPENAI key", bool(cfg.openai.api_key), "Set openai.api_key or OPENAI_API_KEY", True))
        checks.append(("OPENAI model", bool(cfg.openai.model), cfg.openai.model, True))
        checks.append(("OPENAI base_url", bool(cfg.openai.base_url), cfg.openai.base_url, True))
    if cfg.vision.provider == "ollama":
        checks.append(("OLLAMA base_url", bool(cfg.ollama.base_url), cfg.ollama.base_url, True))
        checks.append(("OLLAMA model", bool(cfg.ollama.model), cfg.ollama.model, True))
        checks.append(("OLLAMA num_predict", cfg.ollama.num_predict > 0, str(cfg.ollama.num_predict), True))
        checks.append(("OLLAMA temperature", 0 <= cfg.ollama.temperature <= 2, str(cfg.ollama.temperature), True))
        checks.append(("OLLAMA top_p", 0 < cfg.ollama.top_p <= 1, str(cfg.ollama.top_p), True))
        checks.append(("OLLAMA continuation_attempts", cfg.ollama.continuation_attempts >= 0, str(cfg.ollama.continuation_attempts), True))
        checks.append(("OLLAMA min_paragraphs", cfg.ollama.min_paragraphs >= 1, str(cfg.ollama.min_paragraphs), True))
        checks.append(
            (
                "OLLAMA coverage_retry_attempts",
                cfg.ollama.coverage_retry_attempts >= 0,
                str(cfg.ollama.coverage_retry_attempts),
                True,
            )
        )
        checks.append(
            (
                "OLLAMA num_predict recommendation",
                cfg.ollama.num_predict >= 1200,
                "Use >=1200 for multi-paragraph completeness",
                False,
            )
        )
        checks.append(
            (
                "OLLAMA coverage_retry recommendation",
                cfg.ollama.coverage_retry_attempts >= 1,
                "Use >=1 to auto-retry low paragraph coverage",
                False,
            )
        )
        try:
            base = cfg.ollama.base_url.rstrip("/")
            tags_resp = requests.get(f"{base}/api/tags", timeout=5)
            reachable = tags_resp.status_code < 400
            checks.append(("OLLAMA reachable", reachable, f"GET {base}/api/tags", True))
            model_found = False
            if reachable:
                models = tags_resp.json().get("models", [])
                names = [str(m.get("name", "")) for m in models]
                model = cfg.ollama.model.strip()
                model_found = model in names or f"{model}:latest" in names or model.removesuffix(":latest") in names
            checks.append(("OLLAMA model available", model_found, cfg.ollama.model, True))
        except Exception as exc:  # noqa: BLE001
            checks.append(("OLLAMA reachable", False, str(exc), True))
            checks.append(("OLLAMA model available", False, cfg.ollama.model, True))

    checks.append(("ELEVENLABS key", bool(cfg.elevenlabs.api_key), "Set elevenlabs.api_key or ELEVENLABS_API_KEY", True))
    checks.append(("ELEVENLABS voice_id", bool(cfg.elevenlabs.voice_id), "Set elevenlabs.voice_id or ELEVENLABS_VOICE_ID", True))
    checks.append(("Capture hotkey configured", bool(cfg.capture.hotkey), cfg.capture.hotkey, True))
    checks.append(("Stop hotkey configured", bool(cfg.capture.stop_hotkey), cfg.capture.stop_hotkey, True))
    usage_service = UsageService.from_config(cfg)
    snapshot = usage_service.get_snapshot(force_refresh=True)
    checks.append(
        (
            "OPENAI org usage access",
            snapshot.openai.source == "organization" and snapshot.openai.status == "ok",
            f"source={snapshot.openai.source} status={snapshot.openai.status}",
            False,
        )
    )
    checks.append(
        (
            "ELEVENLABS subscription reachable",
            snapshot.elevenlabs.status == "ok",
            f"status={snapshot.elevenlabs.status}",
            False,
        )
    )
    try:
        is_admin = bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:  # noqa: BLE001
        is_admin = False
    checks.append(
        (
            "Elevated privileges",
            is_admin,
            "Run terminal as Administrator if hotkeys fail in elevated games",
            False,
        )
    )

    all_ok = True
    for name, ok, detail, required in checks:
        status = "OK" if ok else ("FAIL" if required else "WARN")
        print(f"[{status}] {name}: {detail}")
        if required:
            all_ok = all_ok and ok

    return 0 if all_ok else 1


def voices_command(config_path: Path) -> int:
    from snap_narrate.elevenlabs_client import ElevenLabsClient

    cfg = load_config(config_path)
    client = ElevenLabsClient(
        api_key=cfg.elevenlabs.api_key,
        voice_id=cfg.elevenlabs.voice_id,
        model_id=cfg.elevenlabs.model_id,
        output_format=cfg.elevenlabs.output_format,
    )
    voices = client.list_voices()
    for voice_id, name in voices:
        print(f"{name}\t{voice_id}")
    return 0


def test_capture_command(config_path: Path, game_profile: str) -> int:
    from snap_narrate.capture import ScreenCapturer

    cfg = load_config(config_path)
    capturer = ScreenCapturer(
        cooldown_ms=0,
        save_debug=cfg.debug.save_screenshots,
        debug_dir=cfg.debug.screenshot_dir,
    )
    image_bytes = capturer.capture_png()

    extractor = build_extractor(cfg)
    result = extractor.extract_narrative_text(image_bytes=image_bytes, game_profile=game_profile)
    print(f"Confidence: {result.confidence:.2f}")
    if result.dropped_reason:
        print(f"Dropped: {result.dropped_reason}")
    print("Text:")
    print(result.text)
    return 0


def config_init_command(config_path: Path, force: bool) -> int:
    init_config(config_path, force=force)
    print(f"Wrote config: {config_path}")
    return 0


def install_shortcut_command(config_path: Path) -> int:
    manager = ShortcutManager()
    target, args, workdir = launch_command(config_path, include_args=False)
    icon_path = str(icon_asset_path()) if icon_asset_path().exists() else None
    shortcut = manager.create_desktop_shortcut(target=target, arguments=args, working_dir=workdir, icon_path=icon_path)
    print(f"Desktop shortcut created: {shortcut}")
    return 0


def startup_command(config_path: Path, enable: bool, disable: bool, status: bool) -> int:
    target, args, workdir = launch_command(config_path, include_args=False)
    icon_path = str(icon_asset_path()) if icon_asset_path().exists() else None
    manager = StartupManager(ShortcutManager(), target=target, arguments=args, working_dir=workdir, icon_path=icon_path)

    if enable:
        path = manager.enable()
        print(f"Run-at-startup enabled: {path}")
        return 0
    if disable:
        manager.disable()
        print("Run-at-startup disabled")
        return 0

    enabled = manager.is_enabled()
    print(f"Run-at-startup: {'enabled' if enabled else 'disabled'}")
    return 0


def _fmt_usd(value: float | None) -> str:
    if value is None:
        return "unavailable"
    return f"${value:,.4f}"


def usage_command(config_path: Path, as_json: bool = False) -> int:
    cfg = load_config(config_path)
    snapshot = UsageService.from_config(cfg).get_snapshot(force_refresh=True)

    if as_json:
        print(json.dumps(snapshot.to_dict(), indent=2, sort_keys=True))
        return 0 if (snapshot.openai.status == "ok" or snapshot.elevenlabs.status == "ok") else 1

    period = "n/a"
    if snapshot.openai.period_start and snapshot.openai.period_end:
        start = time.strftime("%Y-%m-%d", time.gmtime(snapshot.openai.period_start))
        end = time.strftime("%Y-%m-%d", time.gmtime(snapshot.openai.period_end))
        period = f"{start} .. {end}"

    print("OpenAI")
    print(f"  Status: {snapshot.openai.status}")
    print(f"  Source: {snapshot.openai.source}")
    print(f"  Period: {period}")
    print(
        "  Tokens: total={total} prompt={prompt} completion={completion}".format(
            total=snapshot.openai.total_tokens,
            prompt=snapshot.openai.prompt_tokens,
            completion=snapshot.openai.completion_tokens,
        )
    )
    print(f"  Cost (USD): {_fmt_usd(snapshot.openai.cost_usd)}")
    print(f"  Remaining (USD): {_fmt_usd(snapshot.openai.remaining_usd)}")
    print("")
    print("ElevenLabs")
    print(f"  Status: {snapshot.elevenlabs.status}")
    print(f"  Characters used: {snapshot.elevenlabs.character_count if snapshot.elevenlabs.character_count is not None else 'unavailable'}")
    print(f"  Character limit: {snapshot.elevenlabs.character_limit if snapshot.elevenlabs.character_limit is not None else 'unavailable'}")
    print(
        f"  Remaining characters: {snapshot.elevenlabs.remaining_characters if snapshot.elevenlabs.remaining_characters is not None else 'unavailable'}"
    )
    print(f"  Reset (unix): {snapshot.elevenlabs.next_reset_unix if snapshot.elevenlabs.next_reset_unix is not None else 'unavailable'}")
    return 0 if (snapshot.openai.status == "ok" or snapshot.elevenlabs.status == "ok") else 1


def main(argv: list[str] | None = None) -> int:
    if argv is None:
        argv = sys.argv[1:]

    if len(argv) == 0:
        config_path = resolve_default_config_path()
        if not config_path.exists():
            config_path.parent.mkdir(parents=True, exist_ok=True)
            init_config(config_path, force=True)
        return run_command(config_path=config_path, game_profile="default", auto_launch=True)

    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "run":
        return run_command(args.config, args.game_profile, auto_launch=False)
    if args.command == "doctor":
        return doctor_command(args.config)
    if args.command == "voices":
        return voices_command(args.config)
    if args.command == "test-capture":
        return test_capture_command(args.config, args.game_profile)
    if args.command == "ui":
        target, arg_str, workdir = launch_command(args.config)
        icon_path = str(icon_asset_path()) if icon_asset_path().exists() else None
        startup_manager = StartupManager(
            ShortcutManager(),
            target=target,
            arguments=arg_str,
            working_dir=workdir,
            icon_path=icon_path,
        )
        return launch_settings_ui_with_startup(args.config, startup_manager)
    if args.command == "install-shortcut":
        return install_shortcut_command(args.config)
    if args.command == "startup":
        return startup_command(args.config, args.enable, args.disable, args.status)
    if args.command == "usage":
        return usage_command(args.config, args.as_json)
    if args.command == "config" and args.config_command == "init":
        return config_init_command(args.config, args.force)

    parser.print_help()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())


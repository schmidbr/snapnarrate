"""Command line. With no arguments, starts the tray app (this is what the installed exe does)."""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from pathlib import Path
from typing import Callable

from snap_narrate.config import ConfigStore, init_config, load_config, missing_required
from snap_narrate.paths import default_config_path, is_frozen
from snap_narrate.version import get_app_version

logger = logging.getLogger("snap_narrate")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="snapnarrate", description="Read on-screen game text aloud.")
    parser.add_argument("--version", action="version", version=f"SnapNarrate {get_app_version()}")
    sub = parser.add_subparsers(dest="command")

    def command(name: str, help_text: str, profile: bool = False) -> argparse.ArgumentParser:
        p = sub.add_parser(name, help=help_text)
        p.add_argument("--config", type=Path, default=None, help="config file (default: %%APPDATA%%\\SnapNarrate\\config.toml)")
        if profile:
            p.add_argument("--game-profile", default="default", help="hint passed to the vision model")
        return p

    command("run", "start the tray app", profile=True)
    command("ui", "open the settings window")
    command("doctor", "check configuration and connectivity")
    command("voices", "list ElevenLabs voices for your API key")
    command("test-capture", "capture the screen once and print the extracted text", profile=True)
    command("self-test", "extract and speak a built-in sample page", profile=True)
    startup = command("startup", "manage run at sign-in")
    group = startup.add_mutually_exclusive_group()
    group.add_argument("--enable", action="store_true")
    group.add_argument("--disable", action="store_true")
    usage = command("usage", "show OpenAI usage and ElevenLabs credits")
    usage.add_argument("--json", action="store_true", dest="as_json")
    sub.add_parser("version", help="print the version")
    cfg = sub.add_parser("config", help="config helpers")
    cfg_sub = cfg.add_subparsers(dest="config_command", required=True)
    init = cfg_sub.add_parser("init", help="write a default config")
    init.add_argument("--config", type=Path, default=None)
    init.add_argument("--force", action="store_true")
    path = cfg_sub.add_parser("path", help="print the config path in use")
    path.add_argument("--config", type=Path, default=None)
    return parser


def _config_path(args: argparse.Namespace) -> Path:
    return getattr(args, "config", None) or default_config_path()


# ---- commands ---------------------------------------------------------------------------


def cmd_run(args: argparse.Namespace) -> int:
    from snap_narrate.app import App

    return App(_config_path(args), profile=getattr(args, "game_profile", "default")).run()


def cmd_ui(args: argparse.Namespace) -> int:
    from snap_narrate.ui.settings import run_standalone
    from snap_narrate.windows import StartupManager, enable_dpi_awareness

    enable_dpi_awareness()
    path = _config_path(args)
    return run_standalone(ConfigStore(path), startup=StartupManager(path))


def cmd_doctor(args: argparse.Namespace) -> int:
    import requests

    from snap_narrate import providers
    from snap_narrate.hotkeys import parse_hotkey

    path = _config_path(args)
    cfg = load_config(path)
    results: list[tuple[str, bool, str, bool]] = []  # name, ok, detail, required

    def check(name: str, ok: bool, detail: str = "", required: bool = True) -> None:
        results.append((name, ok, detail, required))

    check("Config file", path.exists(), str(path))
    for warning in cfg.warnings:
        check("Config value", False, warning, required=False)
    missing = missing_required(cfg)
    check("Required settings", not missing, ", ".join(missing) or "all set")
    for key in ("capture.hotkey", "capture.region_hotkey", "capture.stop_hotkey"):
        try:
            parse_hotkey(cfg.get(key))
            check(f"Hotkey {key}", True, cfg.get(key))
        except ValueError as exc:
            check(f"Hotkey {key}", False, str(exc))
    check("Vision provider", cfg.vision.provider in providers.vision_names(), cfg.vision.provider)
    if cfg.env_overrides:
        check("Environment overrides", True, ", ".join(sorted(cfg.env_overrides)), required=False)

    if cfg.vision.provider == "ollama":
        from snap_narrate.providers.ollama import OllamaVision

        try:
            models = OllamaVision(cfg.ollama.base_url, cfg.ollama.model).list_models()
            wanted = cfg.ollama.model
            found = wanted in models or f"{wanted}:latest" in models or wanted.removesuffix(":latest") in models
            check("Ollama reachable", True, cfg.ollama.base_url)
            check("Ollama model installed", found, wanted)
        except Exception as exc:  # noqa: BLE001
            check("Ollama reachable", False, str(exc))
    elif cfg.vision.provider == "ollama-cloud":
        from snap_narrate.config import OLLAMA_CLOUD_URL

        model = cfg.ollama_cloud.model
        try:
            hosted = requests.get(f"{OLLAMA_CLOUD_URL}/api/tags", timeout=10).json().get("models", [])
            check("Ollama Cloud model hosted", model in {m.get("name") for m in hosted}, model)
        except requests.RequestException as exc:
            check("Ollama Cloud reachable", False, str(exc))
        if cfg.ollama_cloud.api_key:
            try:
                # One output token: validates the key for a tiny fraction of a cent.
                response = requests.post(
                    f"{OLLAMA_CLOUD_URL}/api/generate",
                    headers={"Authorization": f"Bearer {cfg.ollama_cloud.api_key}"},
                    json={"model": model, "prompt": "Reply OK.", "stream": False, "think": False, "options": {"num_predict": 1}},
                    timeout=30,
                )
                check("Ollama Cloud key accepted", response.status_code < 400, f"HTTP {response.status_code} {response.text[:120] if response.status_code >= 400 else ''}".strip())
            except requests.RequestException as exc:
                check("Ollama Cloud reachable", False, str(exc))
    elif cfg.vision.provider == "openai" and cfg.openai.api_key:
        try:
            response = requests.get(
                f"{cfg.openai.base_url.rstrip('/')}/v1/models",
                headers={"Authorization": f"Bearer {cfg.openai.api_key}"},
                timeout=10,
            )
            check("OpenAI key accepted", response.status_code < 400, f"HTTP {response.status_code}")
        except requests.RequestException as exc:
            check("OpenAI reachable", False, str(exc))

    if cfg.elevenlabs.api_key:
        try:
            voices = dict(providers.build_speech(cfg).list_voices())  # type: ignore[attr-defined]
            check("ElevenLabs key accepted", True, f"{len(voices)} voices")
            if cfg.elevenlabs.voice_id:
                check("ElevenLabs voice found", cfg.elevenlabs.voice_id in voices, voices.get(cfg.elevenlabs.voice_id, cfg.elevenlabs.voice_id))
        except Exception as exc:  # noqa: BLE001
            check("ElevenLabs key accepted", False, str(exc))

    all_ok = True
    for name, ok, detail, required in results:
        label = "OK  " if ok else ("FAIL" if required else "WARN")
        print(f"[{label}] {name}: {detail}")
        all_ok = all_ok and (ok or not required)
    return 0 if all_ok else 1


def cmd_voices(args: argparse.Namespace) -> int:
    from snap_narrate import providers

    cfg = load_config(_config_path(args))
    for voice_id, name in providers.build_speech(cfg).list_voices():  # type: ignore[attr-defined]
        marker = "*" if voice_id == cfg.elevenlabs.voice_id else " "
        print(f"{marker} {name}\t{voice_id}")
    return 0


def cmd_test_capture(args: argparse.Namespace) -> int:
    from snap_narrate import providers
    from snap_narrate.capture import ScreenCapturer
    from snap_narrate.windows import enable_dpi_awareness

    enable_dpi_awareness()
    cfg = load_config(_config_path(args))
    capturer = ScreenCapturer(0, cfg.capture.max_dimension, cfg.capture.image_format, cfg.capture.jpeg_quality)
    result = providers.build_vision(cfg).extract(capturer.fullscreen(), args.game_profile)
    print(f"Confidence: {result.confidence:.2f}")
    if result.dropped_reason:
        print(f"Note: {result.dropped_reason}")
    print("Text:\n" + result.text)
    return 0


def cmd_self_test(args: argparse.Namespace) -> int:
    from snap_narrate.engine import Engine
    from snap_narrate.logs import setup_logging

    cfg = load_config(_config_path(args))
    setup_logging(cfg.log_path)
    engine = Engine(cfg, profile=f"{args.game_profile}-self-test")
    try:
        result = engine.self_test()
        print(f"Status: {result.status} ({result.message})")
        print(f"Characters: {result.chars}")
        print(f"Timings (ms): extract={result.timings.extract_ms} tts={result.timings.tts_ms} first_audio={result.timings.total_ms}")
        if result.played:
            _wait_for_quiet(lambda: engine.player.is_playing)
        return 0 if result.played else 1
    finally:
        engine.close()


def _wait_for_quiet(is_playing: Callable[[], bool], quiet_sec: float = 3.0, limit_sec: float = 180.0) -> None:
    """Let queued narration finish before the process exits (later chunks arrive in the background)."""
    deadline = time.monotonic() + limit_sec
    quiet_since = time.monotonic()
    while time.monotonic() < deadline:
        if is_playing():
            quiet_since = time.monotonic()
        elif time.monotonic() - quiet_since >= quiet_sec:
            return
        time.sleep(0.1)


def cmd_startup(args: argparse.Namespace) -> int:
    from snap_narrate.windows import StartupManager

    manager = StartupManager(_config_path(args))
    if args.enable:
        manager.enable()
    elif args.disable:
        manager.disable()
    print(f"Run at sign-in: {'enabled' if manager.is_enabled() else 'disabled'}")
    return 0


def cmd_usage(args: argparse.Namespace) -> int:
    from snap_narrate.usage import UsageService

    snap = UsageService.from_config(load_config(_config_path(args))).get_snapshot(force_refresh=True)
    ok = snap.openai.status == "ok" or snap.elevenlabs.status == "ok"
    if args.as_json:
        print(json.dumps(snap.to_dict(), indent=2, sort_keys=True))
        return 0 if ok else 1

    def show(value: object) -> str:
        return "unavailable" if value is None else f"{value:,}" if isinstance(value, int) else str(value)

    o, e = snap.openai, snap.elevenlabs
    print(f"OpenAI ({o.status}, source={o.source})")
    print(f"  Tokens: {o.total_tokens:,} (prompt {o.prompt_tokens:,}, completion {o.completion_tokens:,})")
    print(f"  Cost this month: {'unavailable' if o.cost_usd is None else f'${o.cost_usd:,.4f}'}")
    print(f"  Budget remaining: {'unavailable' if o.remaining_usd is None else f'${o.remaining_usd:,.4f}'}")
    print(f"ElevenLabs ({e.status})")
    print(f"  Characters used: {show(e.character_count)} of {show(e.character_limit)}")
    print(f"  Characters left: {show(e.remaining_characters)}")
    return 0 if ok else 1


def cmd_config(args: argparse.Namespace) -> int:
    path = _config_path(args)
    if args.config_command == "path":
        print(path)
        return 0
    init_config(path, force=args.force)
    print(f"Wrote {path}")
    return 0


COMMANDS: dict[str, Callable[[argparse.Namespace], int]] = {
    "run": cmd_run,
    "ui": cmd_ui,
    "doctor": cmd_doctor,
    "voices": cmd_voices,
    "test-capture": cmd_test_capture,
    "self-test": cmd_self_test,
    "startup": cmd_startup,
    "usage": cmd_usage,
    "config": cmd_config,
    "version": lambda _args: print(f"SnapNarrate {get_app_version()}") or 0,
}


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(sys.argv[1:] if argv is None else argv)
    handler = COMMANDS.get(args.command or "run", cmd_run)
    try:
        return handler(args)
    except KeyboardInterrupt:
        return 130
    except Exception as exc:
        logger.exception("event=fatal command=%s", args.command)
        if is_frozen() and sys.stdout is None:  # windowed exe: nowhere to print
            from snap_narrate.windows import message_box

            message_box(f"SnapNarrate hit an error and has to close:\n\n{exc}", error=True)
            return 1
        raise


def gui_main() -> int:
    """Entry point for the windowed exe and the `snapnarrate-gui` script."""
    return main(sys.argv[1:] or ["run"])

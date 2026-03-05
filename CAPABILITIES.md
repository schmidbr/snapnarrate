# SnapNarrate Capabilities

Last updated: 2026-03-06

## Overview

SnapNarrate v2 is a Windows-first game narrator that captures screenshots, extracts long-form narrative text with either OpenAI or Ollama vision, and plays speech with ElevenLabs.

## Core Capabilities

- Global capture hotkey (default `ctrl+shift+n`)
- Global stop-speaking hotkey (default `ctrl+shift+s`)
- Full-screen screenshot capture with cooldown control
- AI text extraction focused on long-form story/dialog/lore
- Selectable extraction backend via config/UI (`vision.provider = openai|ollama`)
- Ollama two-pass paragraph coverage flow (paragraph collection + finalization)
- Coverage retry guard for low paragraph count (`min_paragraphs`, `coverage_retry_attempts`)
- Filtering to ignore short UI noise (`ignore_short_lines`, `min_block_chars`)
- Text normalization + deduplication (hash/similarity)
- ElevenLabs synthesis with configurable model and output format
- Retry with exponential backoff, then skip on persistent TTS failure
- Audio playback interruption support (`Stop Speaking`)
- Tray controls:
  - Capture Now
  - Stop Speaking
  - Pause/Resume
  - Settings
  - Run At Startup toggle
  - Show Hotkeys
  - Test Voice
  - Usage & Credits
  - Open Logs
  - Exit
- Usage and credits visibility:
  - `usage` CLI command with text/JSON output
  - OpenAI usage/cost best-effort organization fetch with session-token fallback
  - ElevenLabs subscription character credit reporting
  - Configurable usage cache to avoid rate spikes
- Desktop shortcut creation command
- Startup shortcut management (Startup folder-based)
- Tray icon loaded from project `.ico` asset with fallback to generated icon
- No-arg EXE auto-launch path with first-run setup bootstrap
- Desktop settings UI (`ui`) for editing API keys and runtime settings
- CLI workflow:
  - `run`
  - `doctor`
  - `voices`
  - `test-capture`
  - `ui`
  - `install-shortcut`
  - `startup --enable|--disable|--status`
  - `config init`

## Configuration Surface

Managed via `config.toml`:

- `vision.provider`, `vision.timeout_sec`
- `openai.api_key`, `openai.model`, `openai.base_url`
- `openai.admin_api_key`
- `ollama.base_url`, `ollama.model`, `ollama.keep_alive`
- `ollama.num_predict`, `ollama.temperature`, `ollama.top_p`, `ollama.continuation_attempts`
- `ollama.min_paragraphs`, `ollama.coverage_retry_attempts`
- `elevenlabs.api_key`, `elevenlabs.voice_id`, `elevenlabs.model_id`, `elevenlabs.output_format`
- `capture.hotkey`, `capture.stop_hotkey`, `capture.cooldown_ms`
- `filter.min_block_chars`, `filter.ignore_short_lines`
- `dedup.enabled`, `dedup.similarity_threshold`
- `playback.retry_count`, `playback.retry_backoff_ms`
- `debug.save_screenshots`, `debug.screenshot_dir`
- `app.run_at_startup`
- `usage.openai_monthly_budget_usd`, `usage.cache_seconds`
- `log_file`

## Diagnostics and Reliability

- Structured runtime log file at `logs/snapnarrate.log`
- Hotkey registration status surfaced via tray notification and log entries
- `doctor` validates required settings and warns when not elevated
- `doctor` includes warning-level checks for OpenAI org usage endpoint access and ElevenLabs subscription endpoint reachability
- Unit tests cover parser, dedup, pipeline retries, Ollama coverage behavior, startup/shortcut utilities, config round-trip, and audio payload handling

## Current Limitations

- Windows-focused implementation
- Capture mode is full-screen only (no per-window targeting yet)
- Requires network access for OpenAI and ElevenLabs; Ollama local mode requires a local Ollama server
- API keys are currently file/env based (not yet in OS credential vault)
- Output quality depends on game UI readability and model extraction confidence


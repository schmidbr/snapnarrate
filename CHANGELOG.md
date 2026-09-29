# Changelog

All notable changes to this project are documented in this file.

## [Unreleased]

## [0.7.0] - 2026-09-28

### Added

- **Narration history.** Every passage SnapNarrate reads is saved on this PC, newest first, with when and how it was captured. The new History page lets you search, expand, **replay**, copy or delete passages, or clear them all. You can turn history off or set how many passages to keep (default 100). Voice tests and self-tests aren't recorded.
- **Free, instant replay.** The last 10 narrations of the current session replay from their saved audio, with no new ElevenLabs request. Older passages are voiced again.
- **Replay last:** a tray menu item and an optional shortcut (unset by default), plus History… in the tray menu.
- `snapnarrate history [--limit N] [--json]` on the command line, and `GET /v1/history` and `POST /v1/replay` in the local API.

## [0.6.1] - 2026-09-28

### Fixed

- Saving in the new window no longer shows "No installed addon named '[]'". The empty addon list was saved as the text `[]`. Configs affected by this are cleaned up automatically when loaded.

## [0.6.0] - 2026-09-28

A redesigned app window, and volume control for narration.

### Added

- **New SnapNarrate window**, replacing the old Settings dialog. It has sidebar pages (Home, Voice, Reading, Hotkeys, Overlay, Advanced, About), a Windows 11 look that follows your light or dark theme, and sharp scaling on high-DPI displays.
- **Home page:** shows whether SnapNarrate is ready, needs setup, or isn't running, with a button to fix each case. It also has Test voice, Run self-test, and quick settings.
- **Voice picker by name:** voices are listed by name with accent, age, gender and style, and can be searched. Sample playback uses ElevenLabs' free preview clips, so it costs no credits.
- **Shortcut recorder:** click a shortcut and press the new keys. It warns about invalid or duplicate shortcuts, and pauses SnapNarrate's own shortcuts while you record so pressing them doesn't trigger a capture.
- **Narration volume** from 10% to 150%, independent of the Windows volume: a slider that applies live, even mid-sentence, a Volume menu in the tray, and optional louder/quieter shortcuts.
- An unsaved-changes bar with Save and Discard, and a prompt if you close with unsaved changes.
- When the window is opened on its own, it can start SnapNarrate if it isn't already running.

### Changed

- **Reorganized tray menu:** a status line at the top, shortcut hints beside each command, and Volume and Capture submenus. Double-clicking the tray icon opens SnapNarrate. Run at sign-in moved to the Home page.
- Saving settings no longer also shows a Windows notification; the window confirms the save itself.
- The window's background tasks (loading voices, fetching samples) now report back on the UI thread.
- New dependency: CustomTkinter, which provides the modern controls.

## [0.5.1] - 2026-09-28

Changes from the first in-game test of 0.5.0.

### Added

- **Ollama Cloud vision provider** (`ollama-cloud`): metered pay-as-you-go models hosted by Ollama, such as `gemma4:31b`. They use no local GPU, so they don't compete with the game. Set it up with an API key in Settings; `doctor` checks the key and model.
- Ollama requests turn the model's thinking mode off, which lowers latency and, on the cloud, avoids paying for thinking tokens. Token counts are logged per request.
- **Segmented progress bar** in the subtitle overlay. Each segment is one spoken chunk: played segments are full, the current one fills from the real playback position, and upcoming ones are sized from the voice's measured speaking rate. A dim tail marks the part of the passage still being read. It can be turned off with `hud.progress_bar`.
- New events `narration.plan` and `speech.progress`, and `speech.chunk` now includes `index` and `duration`, so API clients such as a future Game Bar widget can draw the same bar.

### Fixed

- **Narration no longer stops after the first sentence.** When the quick first read already returned the whole passage and the model reported nothing more on screen, everything after the first chunk was discarded. The rest of that read is now spoken, with no second read needed.
- A short opening line, such as a speaker name, no longer throws away the first read and triggers a slower second one. It becomes a quick first chunk instead.
- Short real lines at the end of a passage (like "Farewell.") are kept, attached to the chunk before them, instead of being dropped as noise.
- Duplicate detection compares the whole first read, so two dialogues that open with the same speaker line aren't treated as repeats.
- `self-test` from the command line refuses to run while the tray app is running, because two voices would overlap and the tray's Stop couldn't silence the second one.

### Changed

- Build output goes to `%LOCALAPPDATA%\SnapNarrate-build` when the project is inside OneDrive, because sync locks build folders. Override it with `-OutDir`.

## [0.5.0] - 2026-09-28

A cleaner rebuild of the app around a single engine, with fixes for the bugs found in review
and a proper Windows packaging setup. Existing `config.toml` files keep working.

### Fixed

- The app no longer fails to start on Python 3.11. The config writer used backslashes inside an f-string, which only Python 3.12+ accepts.
- **Stop Speaking now really stops.** Previously, the rest of a long narration kept being synthesized in the background and started playing again after Stop.
- **Captures no longer mix.** Taking a new capture while one was still being read could append the old passage's remaining text to the new one.
- Audio in `pcm_16000`, `pcm_22050`, and `pcm_24000` now plays at the correct speed, and 22 kHz MP3 plays instead of producing noise. The output format is now chosen from a supported list.
- API keys supplied through environment variables are no longer copied into `config.toml` when settings are saved.
- Toggling the capture mode from the tray no longer triggers a full reload, which used to stop speech and reset duplicate detection.
- Region selection and the Settings window no longer create Tk windows from different threads, which could hang or crash.
- The first spoken chunk is now capped even when the text has no sentence punctuation.

### Changed

- Hotkeys use the Windows `RegisterHotKey` API instead of a global keyboard hook, so the `keyboard` package is no longer a dependency. No keystrokes are observed, admin rights aren't needed, and antivirus tools are less likely to flag the app.
- Full-screen capture uses the monitor under the mouse cursor instead of always using the primary monitor.
- Every narration, including the non-speech-first path, now speaks its first chunk right away and streams the rest. Stop takes effect within about 50 ms.
- The default voice model for new configs is `eleven_multilingual_v2`, chosen for fidelity. An optional faster first-chunk model can be set.
- Settings are reorganized into tabs. The Voice tab can load your ElevenLabs voices by name and preview them. Values set by environment variables are shown as read-only.
- Run at sign-in uses the per-user registry Run key instead of a Startup-folder shortcut created with PowerShell. An old shortcut is removed automatically.
- Relative paths in the config (such as logs) are resolved relative to the config file. The log file rotates at 1 MB.
- Only one copy of the app can run at a time.
- The Windows build is now a one-folder PyInstaller app with a windowed `SnapNarrate.exe` and a console `snapnarrate-cli.exe`. Both carry version info, the build uses pinned dependencies in an isolated venv, and an Inno Setup script builds a per-user installer.

### Added

- **Subtitle overlay** (`[hud]`): a click-through caption of the line being spoken.
- **Local control API** (`[api]`): token-protected HTTP API on `127.0.0.1` plus a Server-Sent Events stream, for widgets such as a future Xbox Game Bar widget, overlays, and scripts.
- **Addon system:** Python addons through the `snapnarrate.addons` entry point, and a registry for adding vision or speech providers. See `docs/ADDONS.md`.
- Any setting can be overridden with `SNAPNARRATE_<SECTION>_<KEY>` environment variables.
- `snapnarrate config path` command. `doctor` now verifies the API keys and that the selected voice exists.

### Removed

- The `install-shortcut` command. The installer creates Start menu and desktop shortcuts.
- The unused `ollama.continuation_attempts` setting (it is ignored if present) and `requirements.txt`, since `pyproject.toml` is the single source.

## [0.4.2] - 2026-03-31

### Added

- Settings now include a dropdown for choosing the screenshot capture sound from a curated set of built-in Windows sounds.

### Changed

- Capture sound selection is now saved in config and hot-reloads into the tray runtime without requiring a rebuild or manual config edits.

## [0.4.1] - 2026-03-31

### Changed

- Speech-first narration now adapts the first spoken chunk size based on how long the extracted block is and whether more text likely follows, so long passages begin speaking sooner without chopping up short complete passages.
- Screenshot capture feedback now uses the Windows Balloon sound when it is available.

## [0.4.0] - 2026-03-31

### Changed

- Speech-first continuation now uses fuzzy tail alignment so follow-up narration does not replay opening lines when the fast first pass and the full extraction phrase the same text slightly differently.
- Capture feedback now prefers the Windows camera shutter sound effect when it is available.

## [0.3.9] - 2026-03-29

### Changed

- Initial speech-first extraction now returns `more_text_likely`, allowing the pipeline to skip unnecessary second OpenAI/Ollama passes when the first chunk already appears complete.

## [0.3.8] - 2026-03-29

### Changed

- Speech-first continuation now skips the expensive second extraction when the first spoken chunk already looks complete.
- Follow-up narration now uses larger chunk sizes and ignores tiny tails to reduce ElevenLabs request overhead while preserving fast first speech.
- Added config controls for follow-up chunk sizing and minimum follow-up length.

## [0.3.7] - 2026-03-29

### Added

- Ultra-fast trigger mode with separate first-pass extraction prompts and optional dedicated ultra-fast models for OpenAI and Ollama.
- Speech-first playback path that speaks an initial chunk sooner and queues the remaining narration behind it.
- Config fields for ultra-fast extraction models, speech-fast ElevenLabs model selection, and initial speech chunk sizing.

### Changed

- OpenAI, Ollama, and ElevenLabs clients now reuse persistent HTTP sessions instead of opening fresh connections on every request.
- Audio playback now supports queued follow-up chunks so later narration can continue without interrupting the first spoken chunk.

## [0.3.6] - 2026-03-29

### Added

- Fixture-based self-test flow that runs extraction, TTS, and playback through the configured provider path.
- New CLI command: `snapnarrate self-test --config ...`
- New tray action: `Run Self-Test`

### Changed

- Self-tests bypass dedup so they can be repeated without being skipped as duplicate narration.
- Runtime stop-speaking checks now tolerate pipelines without a stoppable player.

## [0.3.5] - 2026-03-29

### Added

- Fast extraction mode toggle for OpenAI and Ollama vision flows.
- Capture sizing controls for max image dimension, upload format, and JPEG quality.

### Changed

- Audio playback now starts non-blocking so new captures do not wait for the previous narration to finish.
- Screenshot uploads now default to resized JPEGs for faster capture-to-extraction turnaround.
- OpenAI vision requests now label JPEG uploads with the correct media type.

## [0.3.4] - 2026-03-29

### Added

- Hotkey notifications for full-screen capture, region capture, and paused capture attempts.
- Capture confirmation sound when a screenshot is successfully taken.
- Latency instrumentation for capture, extraction, TTS, playback, and end-to-end interaction timing.

### Changed

- Versioned test/release builds now align with the latest runtime changes for easier validation.

## [0.3.3] - 2026-03-29

### Changed

- Desktop/startup shortcuts now launch with explicit arguments so they preserve the selected config file.
- Dev-mode shortcut generation now targets `src\main.py`, allowing source-checkout launches without a manual `PYTHONPATH`.
- Dev setup documentation now uses editable install (`pip install -e ".[dev]"`) for working CLI and test commands.

### Fixed

- `py -m pytest -q` now works from the repo root without setting `PYTHONPATH=src`.
- CLI shortcut and startup commands now create working launches for the current app configuration.

## [0.3.2] - 2026-03-05

### Added

- Region capture flow with click-drag selection overlay and dedicated hotkey (`ctrl+shift+r` by default).
- Capture mode controls (`fullscreen`/`region`) with tray mode toggle and `Capture Region Now` action.
- Centralized version resolver with version visibility in tray, settings UI, and CLI.
- New CLI version commands: `snapnarrate version` and `snapnarrate --version`.
- New config fields:
  - `capture.mode`
  - `capture.region_hotkey`
  - `capture.min_region_px`
- Settings UI fields for capture mode/region options and visible app version.
- Unit tests for region capture flow and version reporting.

### Changed

- `doctor` now validates region capture settings (`capture.mode`, `capture.region_hotkey`, `capture.min_region_px`).

## [0.3.1] - 2026-03-05

### Added

- Usage and credits reporting service with normalized OpenAI + ElevenLabs snapshot output.
- New CLI command: `snapnarrate usage [--json]`.
- Tray action: `Usage & Credits` notification summary.
- OpenAI session token usage tracker for fallback reporting when org usage endpoints are unavailable.
- ElevenLabs subscription usage endpoint integration (`/v1/user/subscription`).
- New config fields:
  - `openai.admin_api_key`
  - `usage.openai_monthly_budget_usd`
  - `usage.cache_seconds`
- Settings UI fields for usage/admin-key configuration.
- Unit tests for usage service behavior and config round-trip updates.

### Changed

- `doctor` now includes warning-level checks for OpenAI org usage access and ElevenLabs subscription endpoint reachability.
- Tray item order reorganized to task-first flow for faster access to common actions.

## [0.3.0] - 2026-03-05

### Added

- Configurable vision provider selection (`openai` or `ollama`) via config and settings UI.
- Ollama vision extractor implementation with shared extraction JSON contract.
- Ollama two-pass paragraph coverage extraction with low-coverage retry and merged final output.
- Extractor factory to route provider selection without changing pipeline interfaces.
- Provider-aware `doctor` checks for OpenAI and Ollama setup.
- Windows launchability features:
  - desktop shortcut command
  - startup management command
  - tray startup toggle
  - settings UI startup checkbox
  - startup-folder based autorun support
  - tray icon asset (`assets/snapnarrate.ico`)
  - EXE build script (`scripts/build.ps1`)
  - no-argument EXE auto-run with config auto-discovery and first-run setup UI
  - startup state controls in tray and settings UI (`app.run_at_startup`)

### Changed

- OpenAI extractor now supports configurable `openai.base_url`.
- Config schema expanded with `vision`, `ollama`, OpenAI base URL, startup behavior, and Ollama coverage knobs.
- README/CAPABILITIES updated with provider setup instructions.
- Build script now uses temp workpath and fails fast on PyInstaller errors.

## [0.2.0] - 2026-03-05

### Added

- Full v2 architecture for game narration:
  - screenshot capture service
  - OpenAI vision extraction client
  - ElevenLabs TTS client
  - narration pipeline with filtering and dedup
  - runtime orchestration with worker thread
- System tray app controls and global hotkeys.
- Stop-speaking workflow with dedicated hotkey and tray action.
- Desktop settings UI (`snapnarrate ui`) for editing API keys and app settings.
- Config read/write helpers and richer `config.toml` surface.
- Expanded CLI commands: `run`, `doctor`, `voices`, `test-capture`, `ui`, `config init`.
- Test suite for parser, audio handling, dedup, pipeline behavior, and config round-trip.
- Packaging metadata (`pyproject.toml`).

### Changed

- Migrated from local `pyttsx3` starter behavior to OpenAI + ElevenLabs pipeline.
- Switched ElevenLabs default output format to `mp3_44100_128` for broader plan compatibility.
- Added MP3 decoding playback path and PCM fallback handling.
- Improved runtime diagnostics:
  - hotkey registration status
  - hotkey press/capture queue logs
  - admin/elevation advisory in `doctor`
- Improved UI close behavior (`Close` button + window-close handler).

### Fixed

- `py -m snap_narrate.cli ...` no-op behavior by adding CLI module entrypoint.
- Audio payload handling for non-PCM outputs and malformed payload lengths.
- Settings window close flow requiring force kill.
- Hotkey observability and fallback tray actions for capture troubleshooting.

## [0.1.0] - 2026-03-04

### Added

- Initial project scaffold.
- Basic text-to-speech CLI using local `pyttsx3`.
- Starter files: README, requirements, sample text, git setup.


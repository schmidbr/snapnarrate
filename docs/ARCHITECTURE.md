# Architecture

SnapNarrate is one engine with several interchangeable frontends. Frontends call engine
commands and listen to events on a bus. They never reach into each other.

```
 hotkeys ─┐                           ┌─> tray (notifications, status)
 tray ────┤                           ├─> subtitle overlay (addons/hud.py)
 local API┼─> Engine ── EventBus ─────┼─> local API /v1/events (SSE)
 addons ──┘     │                     └─> your addon
                ├─ ScreenCapturer (capture.py)
                ├─ Narrator (narrator.py)
                │    ├─ VisionProvider  (providers/openai.py, providers/ollama.py, ...)
                │    └─ SpeechProvider  (providers/elevenlabs.py, ...)
                └─ AudioPlayer (audio.py)
```

## Modules

| Module | Responsibility |
|---|---|
| `engine.py` | Thread-safe commands (`capture`, `capture_region`, `speak`, `submit_image`, `stop_speaking`, `set_paused`, `self_test`). Runs one narration at a time; a newer capture replaces a pending one. |
| `narrator.py` | Screenshot → text → speech. Speaks the first chunk right away, then synthesizes the rest in the background. |
| `audio.py` | Decodes ElevenLabs audio and plays a queue of chunks, each tagged with its session. |
| `text.py` | Pure text helpers: normalization, dedup, chunking, and aligning the quick first pass with the full pass. |
| `providers/` | Vision and speech providers plus a registry, so addons can add their own. |
| `config.py` | Dataclass schema. Loading, env overrides, validation, and saving are generic. `ConfigStore` ignores its own writes. |
| `events.py` | Publish/subscribe bus and the topic names. |
| `hotkeys.py` | Win32 `RegisterHotKey` on a message-loop thread. |
| `ui/` | `TkThread` (the only thread that touches Tk), settings window, region picker, tray. |
| `addons/` | Addon host plus the built-in subtitle overlay and local API. |
| `app.py` | Wires everything together and watches the config file for external edits. |
| `windows.py` | Run-at-sign-in (registry), capture sound, single-instance mutex, DPI awareness. |

## Sessions and cancellation

Every narration gets a new `Session`. Starting a narration cancels the previous session, and
`stop_speaking` cancels the current one and clears the player.

- The narrator checks `session.cancelled` before each background extraction and TTS call.
- `AudioPlayer.queue()` rejects chunks from any session that isn't current. A late chunk from
  an old capture can't resume speech after Stop, and can't get mixed into a newer narration.
- Playback is written in ~46 ms blocks and checks the session between blocks, so Stop takes
  effect almost immediately.

## Threads

| Thread | Owns |
|---|---|
| main | App lifecycle and config-file polling |
| `snapnarrate-engine` | Narration worker (extraction and first TTS) |
| `snapnarrate-continuation` | Background TTS for the rest of a narration (one per narration) |
| `snapnarrate-audio` | Audio output |
| `snapnarrate-ui` | Tk: settings window, region picker, subtitle overlay |
| `snapnarrate-hotkeys` | Win32 message loop for hotkeys. Callbacks run on short-lived threads. |
| pystray | Tray icon |

Event handlers run on the publishing thread. UI subscribers must hop to their own thread,
for example with `ui.submit(...)`.

## Packaging

`packaging/snapnarrate.spec` builds a PyInstaller **one-folder** app with two executables
that share one runtime: `SnapNarrate.exe` (windowed) and `snapnarrate-cli.exe` (console).
`packaging/installer.iss` wraps that folder in a per-user Inno Setup installer. The
installer's `AppMutex` matches the app's single-instance mutex, so upgrades close a
running copy cleanly.

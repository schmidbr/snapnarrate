# SnapNarrate

SnapNarrate reads on-screen game text aloud. Press a hotkey and it captures the screen,
uses an AI vision model (Ollama Cloud, OpenAI, or a local Ollama model) to pull out the story text
(dialogue, lore, journals, quest text) while ignoring HUD and menu clutter, then speaks it
with a high-fidelity ElevenLabs voice. Keep playing instead of stopping to read.

## Features

- **Hotkeys:** `Ctrl+Shift+N` reads the screen, `Ctrl+Shift+R` lets you drag a region to read, and `Ctrl+Shift+S` stops speaking. All three are configurable, and no admin rights are needed.
- **Fast start:** a quick first pass starts speaking the first sentence while the full text is still being read. The rest is queued seamlessly.
- **High-fidelity voices:** use any ElevenLabs voice. Voices can be browsed and previewed from Settings. You can optionally use a faster model for just the first sentence.
- **Smart filtering:** skips HUD, menus, and short labels, and doesn't re-read text it just read.
- **Subtitle overlay (optional):** shows the line being spoken over your game, with a segmented progress bar for the whole passage.
- **Local control API (optional):** lets widgets, overlays, Stream Deck buttons, or scripts trigger captures and receive live events. See [docs/ADDONS.md](docs/ADDONS.md).
- **History:** every passage read is saved on your PC. Search it, replay it (instant and free for recent passages), or copy the text. A Replay last shortcut is optional.
- **Narration volume:** set it independently of the Windows volume, so you can turn a quiet game up without the voice getting too loud. Use the slider, the tray's Volume menu, or optional shortcuts.
- **Modern app window:** a Windows 11 look with light and dark themes, a voice picker that shows names and plays free samples, and a shortcut recorder.
- **Tray menu:** read screen or region, stop, volume, capture mode, pause, and tools. Double-click the icon to open SnapNarrate.

## Install

Download `SnapNarrate-Setup-x.y.z.exe` from the releases page and run it. It installs just for
your user account, so no admin prompt appears. On first launch the SnapNarrate window opens. Add:

1. **ElevenLabs API key** on the Voice page. Your voices appear by name; select ▶ to hear a free sample, then click a voice to choose it.
2. **A vision provider** on the Vision tab:
   - `ollama-cloud` (recommended for gaming): pay-as-you-go at [ollama.com](https://ollama.com/pricing).
     Create a key under Settings → Keys and paste it in. It runs on Ollama's servers, so it doesn't
     compete with your game for the GPU. It costs a fraction of a cent per capture with `gemma4:31b`.
   - `openai`: an OpenAI API key.
   - `ollama`: a model on your own PC. It's free, but uses 5–8 GB of graphics memory while you play.

Settings are stored in `%APPDATA%\SnapNarrate\config.toml`.

> Tip: the subtitle overlay only appears over games running in **borderless** or **windowed**
> mode. Exclusive-fullscreen games draw above all other windows.

## Command line

The install folder also contains `snapnarrate-cli.exe`. When running from source, use `python -m snap_narrate`.

| Command | What it does |
|---|---|
| `snapnarrate-cli doctor` | Check config, API keys, voice, and hotkeys |
| `snapnarrate-cli voices` | List your ElevenLabs voices |
| `snapnarrate-cli self-test` | Read and speak a built-in sample page |
| `snapnarrate-cli test-capture` | Capture once and print the extracted text |
| `snapnarrate-cli history [--limit N]` | Recently narrated text |
| `snapnarrate-cli usage [--json]` | OpenAI usage and ElevenLabs credits |
| `snapnarrate-cli startup --enable/--disable` | Run at sign-in |
| `snapnarrate-cli config path` | Show which config file is in use |

Every command accepts `--config PATH`. Any setting can also be supplied through an environment
variable named `SNAPNARRATE_<SECTION>_<KEY>`, for example `SNAPNARRATE_CAPTURE_HOTKEY`. The usual
`OPENAI_API_KEY` and `ELEVENLABS_API_KEY` variables work too. Values that come from the environment
are never written back to the config file.

## Develop

```powershell
py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
pytest
python -m snap_narrate run
```

The code layout and design are described in [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## Build a release

```powershell
.\scripts\build.ps1
```

The script creates an isolated `.venv-build` with the pinned versions in
`packaging/requirements-build.txt`, runs the tests, and builds a `SnapNarrate\` folder with
PyInstaller. That folder holds `SnapNarrate.exe` and `snapnarrate-cli.exe`. If
[Inno Setup 6](https://jrsoftware.org/isinfo.php) is installed (`winget install JRSoftware.InnoSetup`),
it also builds `installer\SnapNarrate-Setup-x.y.z.exe`.

Output goes to `.\dist`. If the project folder is inside OneDrive, it goes to
`%LOCALAPPDATA%\SnapNarrate-build` instead, because OneDrive locks build folders and would upload
about 80 MB per build. Use `-OutDir` to choose another location. To bump the version, edit
`src/snap_narrate/__init__.py`.

For distribution to other people, sign both exes and the installer (for example with Azure
Trusted Signing) to avoid SmartScreen warnings.

## Privacy

Screenshots are sent to the vision provider you choose: Ollama Cloud, OpenAI, or your own local
Ollama server. The extracted text is sent to ElevenLabs. Nothing is sent until you press a capture
hotkey. The local API is off by default. When enabled, it listens only on `127.0.0.1` and
requires a token.

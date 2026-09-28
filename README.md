# SnapNarrate

SnapNarrate reads on-screen game text aloud. Press a hotkey and it captures the screen,
uses an AI vision model (OpenAI, or a local Ollama model) to pull out the story text
(dialogue, lore, journals, quest text) while ignoring HUD and menu clutter, then speaks it
with a high-fidelity ElevenLabs voice. Keep playing instead of stopping to read.

## Features

- **Hotkeys:** `Ctrl+Shift+N` reads the screen, `Ctrl+Shift+R` lets you drag a region to read, and `Ctrl+Shift+S` stops speaking. All three are configurable, and no admin rights are needed.
- **Fast start:** a quick first pass starts speaking the first sentence while the full text is still being read. The rest is queued seamlessly.
- **High-fidelity voices:** use any ElevenLabs voice. Voices can be browsed and previewed from Settings. You can optionally use a faster model for just the first sentence.
- **Smart filtering:** skips HUD, menus, and short labels, and doesn't re-read text it just read.
- **Subtitle overlay (optional):** shows the line being spoken over your game.
- **Local control API (optional):** lets widgets, overlays, Stream Deck buttons, or scripts trigger captures and receive live events. See [docs/ADDONS.md](docs/ADDONS.md).
- **Tray menu:** capture, stop, pause, capture mode, settings, run at sign-in, test voice, self-test, usage and credits, and logs.

## Install

Download `SnapNarrate-Setup-x.y.z.exe` from the releases page and run it. It installs just for
your user account, so no admin prompt appears. On first launch the Settings window opens. Add:

1. **ElevenLabs API key**. Then click **Load voices**, pick a voice, and click **Preview voice**.
2. **OpenAI API key**, or switch the provider to `ollama` and set a local vision model such as `llava`.

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
`packaging/requirements-build.txt`, runs the tests, and builds `dist\SnapNarrate\` with PyInstaller.
That folder holds `SnapNarrate.exe` and `snapnarrate-cli.exe`. If
[Inno Setup 6](https://jrsoftware.org/isinfo.php) is installed (`winget install JRSoftware.InnoSetup`),
it also builds `dist\installer\SnapNarrate-Setup-x.y.z.exe`. To bump the version, edit
`src/snap_narrate/__init__.py`.

For distribution to other people, sign both exes and the installer (for example with Azure
Trusted Signing) to avoid SmartScreen warnings.

## Privacy

Screenshots are sent to the vision provider you choose: OpenAI, or your own local Ollama
server. The extracted text is sent to ElevenLabs. Nothing is sent until you press a capture
hotkey. The local API is off by default. When enabled, it listens only on `127.0.0.1` and
requires a token.

# Extending SnapNarrate

There are two ways to build on SnapNarrate:

- **Out-of-process: the local API.** This works from any language and any process, and it's the
  way to build a Game Bar widget, an overlay app, a Stream Deck plugin, or a script. It also
  works with the installed exe.
- **In-process: Python addons.** An addon runs inside SnapNarrate, can add vision or speech
  providers, and can create Tk windows. It needs a Python install of SnapNarrate (pip or
  source), because the frozen exe can't load packages installed later.

## Local API

Turn it on in **Settings → Overlay & API**, or set `[api] enabled = true` in the config. It listens on
`http://127.0.0.1:47811` (the port is configurable) and nowhere else.

Every request needs the token from `%APPDATA%\SnapNarrate\api_token.txt`, sent in one of two ways:

- as the header `Authorization: Bearer <token>`, or
- as the query parameter `?token=<token>`, for clients like `EventSource` that can't set headers.

| Method & path | Body | Effect |
|---|---|---|
| `GET /v1/status` | none | `{"version", "state", "paused", "capture_mode"}` |
| `POST /v1/capture` | `{"mode": "fullscreen" \| "region"}` (optional) | Capture and read. With no mode, the configured mode is used. |
| `POST /v1/stop` | none | Stop speaking |
| `POST /v1/pause` | `{"paused": true \| false}` (omit to toggle) | Pause or resume hotkey captures |
| `POST /v1/speak` | `{"text": "..."}` | Speak the given text with the configured voice |
| `POST /v1/narrate-image` | raw PNG or JPEG, `Content-Type: image/png` or `image/jpeg` | Read your own screenshot (for example one taken by a widget) |
| `GET /v1/events` | none | Server-Sent Events stream of everything below |

Commands return `202` right away. Follow progress on the event stream.

### Events

Each event arrives as `event: <topic>` followed by `data: {"topic", "data", "ts"}`.

| Topic | `data` |
|---|---|
| `status` | `state` (`idle`, `capturing`, `extracting`, `speaking`), `paused`, `capture_mode` |
| `capture` | `source`, `bytes`, `capture_ms` |
| `narration.started` | `session`, `source` |
| `narration.text` | `session`, `text`, `final`: the text being read. It may arrive twice, once with the first paragraph and again with the full text. |
| `narration.plan` | `session`, `chunk_chars` (character count per chunk, in playback order), `final`. When `final` is false, more chunks may still be added; the plan is re-sent with the full list once the rest of the passage has been read. |
| `speech.chunk` | `session`, `index`, `text`, `duration` (seconds): this chunk just started playing. Use it for subtitles. |
| `speech.progress` | `session`, `index`, `position`, `duration` (seconds), about 10 times a second while audio plays |
| `speech.idle` | none: playback finished or was stopped |
| `narration.finished` | `session`, `status` (`played`, `skipped`, `failed`, `cancelled`), `message`, `chars`, `timings` |
| `notice` | `message`, `level`: the messages the tray shows as notifications |

To draw a progress bar from these events, `snap_narrate.progress.ProgressTracker` holds the
logic the subtitle overlay uses: one segment per chunk, with upcoming chunks sized from the
voice's measured speaking rate. It is plain Python with no UI, so it's easy to port.

### Example: PowerShell

```powershell
$token = Get-Content "$env:APPDATA\SnapNarrate\api_token.txt"
Invoke-RestMethod -Method Post http://127.0.0.1:47811/v1/capture -Headers @{Authorization = "Bearer $token"}
```

### Example: live subtitles in a browser page

```js
const events = new EventSource(`http://127.0.0.1:47811/v1/events?token=${token}`);
events.addEventListener("speech.chunk", (e) => show(JSON.parse(e.data).data.text));
events.addEventListener("speech.idle", () => hide());
```

## Xbox Game Bar widget (planned)

Game Bar widgets are UWP apps built with the Xbox Game Bar SDK (C# or C++/WinRT). The
intended design is a thin widget that drives SnapNarrate through the local API:

- **Buttons:** Read screen, Read region, Stop, Pause call `POST /v1/capture`, `/v1/stop`, and `/v1/pause`.
- **Subtitle panel:** subscribes to `/v1/events` and shows `speech.chunk` text.
- **Status:** reflects the `status` events.

Things to check when building it:

- **Loopback access.** UWP apps can't connect to `127.0.0.1` by default. The usual
  options are to package the widget together with SnapNarrate as its full-trust companion
  (MSIX with a desktop extension, communicating over an AppService), or to use a loopback
  exemption during development. Check the current Game Bar SDK guidance before choosing.
- **Token access.** The widget has to read the token. If the widget and SnapNarrate share an
  MSIX package, the companion can pass it over the AppService connection instead.

## Python addons

An addon is any object with a `name`, `start(ctx)`, and `stop()`:

```python
from snap_narrate import events
from snap_narrate.addons import AddonContext


class ChatLog:
    name = "chat_log"

    def start(self, ctx: AddonContext) -> None:
        path = ctx.data_dir / "narration-log.txt"

        def write(event: events.Event) -> None:
            if event.data.get("final"):
                with path.open("a", encoding="utf-8") as fh:
                    fh.write(event.data["text"] + "\n\n")

        self._unsubscribe = ctx.bus.subscribe(events.NARRATION_TEXT, write)

    def stop(self) -> None:
        self._unsubscribe()
```

Register it in your package's `pyproject.toml`:

```toml
[project.entry-points."snapnarrate.addons"]
chat_log = "my_package.chat_log:ChatLog"
```

Then enable it in SnapNarrate's config:

```toml
[addons]
extra = ["chat_log"]
```

`AddonContext` provides:

- `engine`: the same commands the tray uses.
- `bus`: the event bus.
- `config`: the current `AppConfig`.
- `ui`: the Tk thread. Create windows only through `ctx.ui.submit(fn)`.
- `data_dir`: `%APPDATA%\SnapNarrate`.

Addons are restarted whenever settings change.

### Adding a provider

```python
from snap_narrate.providers import register_vision

register_vision("my_ocr", lambda cfg: MyOcrVision())  # then set [vision] provider = "my_ocr"
```

A vision provider implements `extract(image, profile)` and `extract_first(image, profile)`,
and returns `ExtractResult`. A speech provider implements `synthesize(text, fast=False)`
and has an `output_format` attribute. See `providers/base.py`.

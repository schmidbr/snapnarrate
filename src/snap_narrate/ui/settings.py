"""Settings window. Fields are declared once in TABS; loading, validation, and saving are generic."""

from __future__ import annotations

import logging
import threading
import tkinter as tk
from dataclasses import dataclass
from tkinter import messagebox, ttk
from typing import Callable

from snap_narrate.config import (
    CAPTURE_MODES,
    SUPPORTED_OUTPUT_FORMATS,
    VISION_PROVIDERS,
    WINDOWS_CAPTURE_SOUND_OPTIONS,
    AppConfig,
    ConfigStore,
    coerce,
    iter_settings,
)
from snap_narrate.hotkeys import parse_hotkey
from snap_narrate.version import get_app_version

logger = logging.getLogger("snap_narrate")

ELEVENLABS_MODELS = ["eleven_multilingual_v2", "eleven_v3", "eleven_turbo_v2_5", "eleven_flash_v2_5"]
PREVIEW_TEXT = "The old observatory stood silent above the valley. This is how SnapNarrate will sound."


@dataclass
class Field:
    key: str
    label: str
    kind: str = "text"  # text | secret | bool | choice | combo | voice | hotkey
    choices: tuple[str, ...] = ()
    hint: str = ""


TABS: list[tuple[str, list[Field]]] = [
    (
        "Voice",
        [
            Field("elevenlabs.api_key", "ElevenLabs API key", "secret"),
            Field("elevenlabs.voice_id", "Voice", "voice", hint="Load voices to pick by name, or paste a voice ID"),
            Field("elevenlabs.model_id", "Voice model", "combo", tuple(ELEVENLABS_MODELS), "multilingual_v2 / v3 = highest fidelity"),
            Field("elevenlabs.speech_fast_model_id", "First-chunk model", "combo", ("", *ELEVENLABS_MODELS), "Optional faster model for the first sentence"),
            Field("elevenlabs.output_format", "Audio format", "choice", tuple(SUPPORTED_OUTPUT_FORMATS)),
        ],
    ),
    (
        "Vision",
        [
            Field("vision.provider", "Provider", "combo", tuple(VISION_PROVIDERS), "ollama-cloud = pay-as-you-go, no GPU use"),
            Field("ollama_cloud.api_key", "Ollama Cloud API key", "secret", hint="ollama.com → Settings → Keys"),
            Field("ollama_cloud.model", "Ollama Cloud model", "combo", ("gemma4:31b", "glm-5.3-flash", "deepseek-v4.1-flash", "mistral-large-3:675b")),
            Field("openai.api_key", "OpenAI API key", "secret"),
            Field("openai.model", "OpenAI model"),
            Field("openai.ultra_fast_model", "OpenAI first-pass model", hint="Optional faster model for the first paragraph"),
            Field("openai.base_url", "OpenAI base URL", hint="Any OpenAI-compatible endpoint"),
            Field("ollama.base_url", "Local Ollama URL"),
            Field("ollama.model", "Local Ollama model"),
            Field("ollama.ultra_fast_model", "Local Ollama first-pass model"),
            Field("vision.timeout_sec", "Timeout (seconds)"),
            Field("vision.fast_mode", "Fast extraction", "bool"),
            Field("vision.ultra_fast_mode", "Ultra-fast first pass", "bool"),
        ],
    ),
    (
        "Capture",
        [
            Field("capture.hotkey", "Capture hotkey", "hotkey"),
            Field("capture.region_hotkey", "Region hotkey", "hotkey"),
            Field("capture.stop_hotkey", "Stop hotkey", "hotkey"),
            Field("capture.mode", "Default capture", "choice", tuple(CAPTURE_MODES)),
            Field("capture.sound_name", "Capture sound", "choice", tuple(WINDOWS_CAPTURE_SOUND_OPTIONS)),
            Field("capture.cooldown_ms", "Cooldown (ms)"),
            Field("capture.min_region_px", "Min region size (px)"),
            Field("capture.max_dimension", "Max image size (px, 0 = full)"),
            Field("capture.image_format", "Image format", "choice", ("jpeg", "png")),
            Field("capture.jpeg_quality", "JPEG quality"),
        ],
    ),
    (
        "Reading",
        [
            Field("playback.speech_first_enabled", "Start speaking before the full read finishes", "bool"),
            Field("playback.initial_chunk_chars", "First chunk (chars)"),
            Field("playback.followup_chunk_chars", "Later chunks (chars)"),
            Field("playback.followup_min_chars", "Skip trailing fragments under (chars)"),
            Field("filter.min_block_chars", "Ignore text shorter than (chars)"),
            Field("filter.ignore_short_lines", "Ignore lines with fewer words than"),
            Field("dedup.enabled", "Skip text that was just read", "bool"),
            Field("dedup.similarity_threshold", "Repeat similarity (0-1)"),
            Field("playback.retry_count", "Voice retries"),
            Field("playback.retry_backoff_ms", "Retry backoff (ms)"),
        ],
    ),
    (
        "Overlay & API",
        [
            Field("hud.enabled", "Show subtitles overlay while speaking", "bool"),
            Field("hud.position", "Overlay position", "choice", ("bottom", "top")),
            Field("hud.font_size", "Overlay font size"),
            Field("hud.opacity", "Overlay opacity (0.2-1)"),
            Field("hud.linger_ms", "Keep overlay after speech (ms)"),
            Field("hud.progress_bar", "Show playback progress bar in the overlay", "bool"),
            Field("api.enabled", "Enable local control API (for widgets and tools)", "bool"),
            Field("api.port", "API port"),
        ],
    ),
    (
        "Advanced",
        [
            Field("ollama.keep_alive", "Ollama keep-alive"),
            Field("ollama.num_predict", "Ollama max tokens"),
            Field("ollama.temperature", "Ollama temperature"),
            Field("ollama.top_p", "Ollama top_p"),
            Field("ollama.min_paragraphs", "Ollama min paragraphs"),
            Field("ollama.coverage_retry_attempts", "Ollama coverage retries"),
            Field("openai.admin_api_key", "OpenAI admin key (usage)", "secret"),
            Field("usage.openai_monthly_budget_usd", "OpenAI monthly budget (USD)"),
            Field("debug.save_screenshots", "Save debug screenshots", "bool"),
            Field("debug.screenshot_dir", "Screenshot folder"),
            Field("log_file", "Log file"),
        ],
    ),
]


class SettingsWindow:
    def __init__(
        self,
        master: tk.Misc,
        store: ConfigStore,
        on_saved: Callable[[AppConfig], None] | None = None,
        on_closed: Callable[[], None] | None = None,
        startup: object | None = None,
    ) -> None:
        self.store = store
        self.on_saved = on_saved
        self.on_closed = on_closed
        self.startup = startup
        self.cfg = store.load()
        self.types = dict(iter_settings())
        self.vars: dict[str, tk.Variable] = {}
        self._preview_player = None

        self.win = tk.Toplevel(master)
        self.win.title(f"SnapNarrate {get_app_version()} Settings")
        self.win.geometry("640x560")
        self.win.minsize(560, 480)
        self.win.protocol("WM_DELETE_WINDOW", self.close)
        self._build()
        self.win.lift()
        self.win.focus_force()

    # ---- layout -----------------------------------------------------------------------

    def _build(self) -> None:
        notebook = ttk.Notebook(self.win)
        notebook.pack(fill=tk.BOTH, expand=True, padx=10, pady=(10, 0))
        for title, fields in TABS:
            frame = ttk.Frame(notebook, padding=12)
            frame.columnconfigure(1, weight=1)
            notebook.add(frame, text=title)
            for row, spec in enumerate(fields):
                self._add_field(frame, row, spec)
            if title == "Voice":
                self._add_voice_actions(frame, len(fields))
            if title == "Advanced" and self.startup is not None:
                var = tk.BooleanVar(value=self._startup_enabled())
                self.vars["__startup__"] = var
                ttk.Checkbutton(frame, text="Run SnapNarrate when I sign in", variable=var).grid(
                    row=len(fields), column=0, columnspan=3, sticky="w", pady=(10, 0)
                )

        buttons = ttk.Frame(self.win, padding=10)
        buttons.pack(fill=tk.X)
        ttk.Label(buttons, text=f"Config: {self.store.path}", foreground="#666").pack(side=tk.LEFT)
        ttk.Button(buttons, text="Save & Close", command=self._save_and_close).pack(side=tk.RIGHT)
        ttk.Button(buttons, text="Save", command=self._save).pack(side=tk.RIGHT, padx=6)
        ttk.Button(buttons, text="Cancel", command=self.close).pack(side=tk.RIGHT)

    def _add_field(self, parent: ttk.Frame, row: int, spec: Field) -> None:
        value = self.cfg.get(spec.key)
        from_env = spec.key in self.cfg.env_overrides
        ttk.Label(parent, text=spec.label).grid(row=row, column=0, sticky="w", pady=3, padx=(0, 10))
        state = "disabled" if from_env else "normal"

        if spec.kind == "bool":
            var: tk.Variable = tk.BooleanVar(value=bool(value))
            widget: tk.Widget = ttk.Checkbutton(parent, variable=var, state=state)
        else:
            var = tk.StringVar(value="" if value is None else str(value))
            if spec.kind == "choice":
                widget = ttk.Combobox(parent, textvariable=var, values=spec.choices, state="disabled" if from_env else "readonly")
            elif spec.kind in {"combo", "voice"}:
                widget = ttk.Combobox(parent, textvariable=var, values=spec.choices, state=state)
                if spec.kind == "voice":
                    self._voice_combo = widget
                    widget.bind("<<ComboboxSelected>>", self._on_voice_selected)
            else:
                widget = ttk.Entry(parent, textvariable=var, show="•" if spec.kind == "secret" else "", state=state)
        widget.grid(row=row, column=1, sticky="ew" if spec.kind != "bool" else "w", pady=3)
        self.vars[spec.key] = var

        note = "set by environment variable" if from_env else spec.hint
        if note:
            ttk.Label(parent, text=note, foreground="#777").grid(row=row, column=2, sticky="w", padx=(8, 0))

    def _add_voice_actions(self, parent: ttk.Frame, row: int) -> None:
        actions = ttk.Frame(parent)
        actions.grid(row=row, column=1, sticky="w", pady=(10, 0))
        ttk.Button(actions, text="Load voices", command=self._load_voices).pack(side=tk.LEFT)
        ttk.Button(actions, text="Preview voice", command=self._preview_voice).pack(side=tk.LEFT, padx=6)
        self._voice_status = ttk.Label(parent, text="", foreground="#777")
        self._voice_status.grid(row=row + 1, column=1, sticky="w")

    # ---- voice helpers ----------------------------------------------------------------

    def _speech_from_form(self):  # noqa: ANN202
        from snap_narrate.providers.elevenlabs import ElevenLabsSpeech

        return ElevenLabsSpeech(
            api_key=str(self.vars["elevenlabs.api_key"].get()).strip() or self.cfg.elevenlabs.api_key,
            voice_id=str(self.vars["elevenlabs.voice_id"].get()).strip(),
            model_id=str(self.vars["elevenlabs.model_id"].get()).strip(),
            output_format=str(self.vars["elevenlabs.output_format"].get()).strip(),
            timeout_sec=30,
        )

    def _in_background(self, work: Callable[[], object], done: Callable[[object], None], busy: str) -> None:
        self._voice_status.config(text=busy)

        def run() -> None:
            try:
                result: object = work()
            except Exception as exc:  # noqa: BLE001
                result = exc
            self.win.after(0, lambda: done(result))

        threading.Thread(target=run, daemon=True).start()

    def _load_voices(self) -> None:
        speech = self._speech_from_form()

        def done(result: object) -> None:
            if isinstance(result, Exception):
                self._voice_status.config(text=f"Could not load voices: {result}")
                return
            voices = result  # list[(id, name)]
            self._voice_combo.configure(values=[f"{name}  ({voice_id})" for voice_id, name in voices])  # type: ignore[union-attr]
            self._voice_status.config(text=f"{len(voices)} voices loaded. Pick one from the list.")  # type: ignore[arg-type]

        self._in_background(speech.list_voices, done, "Loading voices…")

    def _on_voice_selected(self, _event: object) -> None:
        picked = str(self.vars["elevenlabs.voice_id"].get())
        if picked.endswith(")") and "(" in picked:
            self.vars["elevenlabs.voice_id"].set(picked[picked.rfind("(") + 1 : -1])

    def _preview_voice(self) -> None:
        speech = self._speech_from_form()

        def done(result: object) -> None:
            if isinstance(result, Exception):
                self._voice_status.config(text=f"Preview failed: {result}")
                return
            from snap_narrate.audio import AudioPlayer

            if self._preview_player is None:
                self._preview_player = AudioPlayer(speech.output_format)
            self._preview_player.output_format = speech.output_format
            try:
                self._preview_player.play(result, session=1)  # type: ignore[arg-type]
                self._voice_status.config(text="Playing preview…")
            except Exception as exc:  # noqa: BLE001
                self._voice_status.config(text=f"Preview failed: {exc}")

        self._in_background(lambda: speech.synthesize(PREVIEW_TEXT), done, "Generating preview…")

    # ---- save -------------------------------------------------------------------------

    def _startup_enabled(self) -> bool:
        try:
            return bool(self.startup.is_enabled())  # type: ignore[union-attr]
        except Exception:  # noqa: BLE001
            return False

    def _collect(self) -> AppConfig:
        cfg = self.store.load()
        errors: list[str] = []
        for key, var in self.vars.items():
            if key.startswith("__") or key in cfg.env_overrides:
                continue
            raw = var.get()
            try:
                cfg.set(key, coerce(raw.strip() if isinstance(raw, str) else raw, self.types[key]))
            except (TypeError, ValueError) as exc:
                errors.append(f"{key}: {exc}")
        for key in ("capture.hotkey", "capture.region_hotkey", "capture.stop_hotkey"):
            try:
                parse_hotkey(cfg.get(key))
            except ValueError as exc:
                errors.append(f"{key}: {exc}")
        if errors:
            raise ValueError("\n".join(errors))
        return cfg

    def _save(self) -> bool:
        try:
            cfg = self._collect()
            self.store.save(cfg)
            cfg = self.store.load()  # re-read so normalization and env overrides apply
            if "__startup__" in self.vars:
                self.startup.set(bool(self.vars["__startup__"].get()))  # type: ignore[union-attr]
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("Could not save settings", str(exc), parent=self.win)
            return False
        for warning in cfg.warnings:
            logger.warning("event=config_warning %s", warning)
        if self.on_saved is not None:
            self.on_saved(cfg)
        return True

    def _save_and_close(self) -> None:
        if self._save():
            self.close()

    def close(self) -> None:
        if self._preview_player is not None:
            self._preview_player.close()
        self.win.destroy()
        if self.on_closed is not None:
            self.on_closed()


def run_standalone(store: ConfigStore, startup: object | None = None) -> int:
    """`snapnarrate ui`: the settings window as its own process."""
    root = tk.Tk()
    root.withdraw()
    store.ensure_exists()
    SettingsWindow(root, store, startup=startup, on_closed=root.quit)
    root.mainloop()
    root.destroy()
    return 0

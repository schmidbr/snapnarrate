"""SnapNarrate's main window: status, voice, reading, hotkeys, overlay, advanced, about.

Every setting is a Tk variable keyed by its dotted config path. Pages are built lazily and
only arrange controls around those variables, so saving is generic: coerce each variable
to its schema type, validate, write. Background work (loading voices, fetching samples)
hands results back through `self.post`, which runs them on the UI thread.
"""

from __future__ import annotations

import logging
import queue
import tkinter as tk
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from tkinter import messagebox
from typing import Any, Callable

import customtkinter as ctk
from PIL import Image, ImageDraw, ImageFont

from snap_narrate.config import (
    WINDOWS_CAPTURE_SOUND_OPTIONS,
    AppConfig,
    ConfigStore,
    coerce,
    iter_settings,
    missing_required,
)
from snap_narrate.hotkeys import keycaps
from snap_narrate.paths import icon_path, user_data_dir
from snap_narrate.ui import theme as t
from snap_narrate.ui.widgets import (
    Card,
    HotkeyRecorder,
    LabeledOption,
    LinkLabel,
    Segmented,
    Slider,
    TextField,
    button,
    hotkey_problem,
    run_in_background,
    section,
    switch,
)
from snap_narrate.version import get_app_version

logger = logging.getLogger("snap_narrate")

PREVIEW_TEXT = "The old observatory stood silent above the valley. This is how SnapNarrate will sound."

VOICE_MODELS = [
    ("eleven_multilingual_v2", "Multilingual v2 · highest fidelity"),
    ("eleven_v3", "Eleven v3 · most expressive"),
    ("eleven_turbo_v2_5", "Turbo v2.5 · fast"),
    ("eleven_flash_v2_5", "Flash v2.5 · fastest"),
]
FIRST_CHUNK_MODELS = [("", "Same as voice model"), *VOICE_MODELS]
AUDIO_FORMATS = [
    ("mp3_44100_128", "MP3 · 128 kbps (recommended)"),
    ("mp3_44100_192", "MP3 · 192 kbps · paid plans"),
    ("mp3_44100_64", "MP3 · 64 kbps"),
    ("mp3_22050_32", "MP3 · 32 kbps · smallest"),
    ("pcm_24000", "PCM · 24 kHz"),
    ("pcm_44100", "PCM · 44.1 kHz · paid plans"),
    ("pcm_22050", "PCM · 22 kHz"),
    ("pcm_16000", "PCM · 16 kHz"),
]
CLOUD_MODELS = [
    ("gemma4:31b", "Gemma 4 31B · lowest cost"),
    ("glm-5.3-flash", "GLM 5.3 Flash · fast"),
    ("deepseek-v4.1-flash", "DeepSeek V4.1 Flash"),
    ("mistral-large-3:675b", "Mistral Large 3 · most capable"),
]
PROVIDERS = [
    ("ollama-cloud", "Ollama Cloud", "Pay as you go. Runs on Ollama's servers, so it never competes with your game for the GPU."),
    ("openai", "OpenAI", "Pay as you go with an OpenAI API key."),
    ("ollama", "Ollama on this PC", "Free, but uses 5-8 GB of graphics memory while you play."),
]
CAPTURE_MODES = [("fullscreen", "Full screen"), ("region", "Region")]
SOUNDS = [(name, name) for name in WINDOWS_CAPTURE_SOUND_OPTIONS]
PAGES = [
    ("home", "Home", "home"),
    ("voice", "Voice", "voice"),
    ("reading", "Reading", "reading"),
    ("hotkeys", "Hotkeys", "keyboard"),
    ("overlay", "Overlay", "overlay"),
    ("advanced", "Advanced", "advanced"),
    ("about", "About", "about"),
]
HOTKEY_KEYS = [
    "capture.hotkey",
    "capture.region_hotkey",
    "capture.stop_hotkey",
    "capture.volume_up_hotkey",
    "capture.volume_down_hotkey",
]
OPTIONAL_HOTKEYS = {"capture.volume_up_hotkey", "capture.volume_down_hotkey"}
MISSING_TO_PAGE = {
    "ElevenLabs API key": "voice",
    "ElevenLabs voice": "voice",
    "OpenAI API key": "reading",
    "Ollama model": "reading",
    "Ollama Cloud API key": "reading",
}
STARTUP_KEY = "__startup__"


@dataclass
class WindowActions:
    """What the window can ask of the running app. All optional: `snapnarrate ui` runs standalone."""

    app_running: Callable[[], bool] = lambda: False
    start_app: Callable[[], None] | None = None
    test_voice: Callable[[], None] | None = None
    run_self_test: Callable[[], None] | None = None
    pause_hotkeys: Callable[[bool], None] | None = None
    set_volume: Callable[[float], None] | None = None


@lru_cache(maxsize=64)
def glyph_image(glyph: str, size: int, color: str) -> Image.Image:
    """Render a Segoe Fluent Icons glyph to a transparent image (drawn at 3x for crisp scaling)."""
    scale = 3
    canvas = Image.new("RGBA", (size * scale, size * scale), (0, 0, 0, 0))
    for name in ("SegoeIcons.ttf", "segmdl2.ttf"):
        try:
            font = ImageFont.truetype(name, int(size * scale * 0.85))
            break
        except OSError:
            continue
    else:
        return canvas
    ImageDraw.Draw(canvas).text((size * scale / 2, size * scale / 2), glyph, font=font, fill=color, anchor="mm")
    return canvas


def icon(name: str, size: int = 16, colors: tuple[str, str] = t.TEXT) -> ctk.CTkImage:
    glyph = t.ICONS[name]
    return ctk.CTkImage(glyph_image(glyph, size, colors[0]), glyph_image(glyph, size, colors[1]), size=(size, size))


def friendly(dotted: str) -> str:
    return dotted.split(".")[-1].replace("_", " ").capitalize()


class SettingsWindow:
    def __init__(
        self,
        master: tk.Misc,
        store: ConfigStore,
        on_saved: Callable[[AppConfig], None] | None = None,
        on_closed: Callable[[], None] | None = None,
        startup: Any = None,
        actions: WindowActions | None = None,
        page: str = "home",
        voice_source: Callable[[str], Any] | None = None,
    ) -> None:
        t.init()
        self.store = store
        self.on_saved = on_saved
        self.on_closed = on_closed
        self.startup = startup
        self.actions = actions or WindowActions()
        self.cfg = store.load()
        self.fonts = t.Fonts()
        self.types = dict(iter_settings())
        self.titles: dict[str, str] = {}
        self.vars: dict[str, tk.Variable] = {}
        self._inbox: queue.Queue[Callable[[], None]] = queue.Queue()
        self._voice_source = voice_source
        self._voices: list[Any] | None = None
        self._voice_error = ""
        self._preview_player: Any = None
        self._pages: dict[str, ctk.CTkScrollableFrame] = {}
        self._nav: dict[str, tuple[ctk.CTkButton, ctk.CTkFrame]] = {}
        self._current = ""
        self._home_job: str | None = None
        self._flash_job: str | None = None
        self._closed = False

        self.win = ctk.CTkToplevel(master, fg_color=t.WINDOW_BG)
        self.win.title("SnapNarrate")
        self.win.geometry("1000x700")
        self.win.minsize(880, 580)
        self.win.protocol("WM_DELETE_WINDOW", self.close)
        # CustomTkinter sets its own icon shortly after creating a toplevel; replace it afterwards.
        self.win.after(300, self._set_icon)

        self._build_vars()
        self._build_shell()
        self._snapshot = self._values()
        for key, var in self.vars.items():
            var.trace_add("write", lambda *_a, k=key: self._changed(k))
        self.show(page)
        self._refresh_footer()
        self._poll_inbox()
        self.win.after(50, self._bring_forward)

    # ---- plumbing ---------------------------------------------------------------------

    def post(self, fn: Callable[[], None]) -> None:
        """Run fn on the UI thread. Safe to call from any thread."""
        self._inbox.put(fn)

    def _poll_inbox(self) -> None:
        if self._closed:
            return
        while True:
            try:
                fn = self._inbox.get_nowait()
            except queue.Empty:
                break
            try:
                fn()
            except Exception:  # noqa: BLE001
                logger.exception("event=settings_callback_failed")
        self.win.after(40, self._poll_inbox)

    def _set_icon(self) -> None:
        try:
            self.win.iconbitmap(str(icon_path()))
        except tk.TclError:
            pass

    def _bring_forward(self) -> None:
        self.win.lift()
        self.win.focus_force()

    def _build_vars(self) -> None:
        for dotted, hint in self.types.items():
            value = self.cfg.get(dotted)
            if hint is bool:
                self.vars[dotted] = tk.BooleanVar(self.win, value=bool(value))
            elif isinstance(value, list):
                # Lists edit as "a, b" text; str(list) would save "[]" back as an item.
                self.vars[dotted] = tk.StringVar(self.win, value=", ".join(str(item) for item in value))
            else:
                self.vars[dotted] = tk.StringVar(self.win, value="" if value is None else str(value))
        enabled = False
        if self.startup is not None:
            try:
                enabled = bool(self.startup.is_enabled())
            except Exception:  # noqa: BLE001
                enabled = False
        self.vars[STARTUP_KEY] = tk.BooleanVar(self.win, value=enabled)

    def _values(self) -> dict[str, Any]:
        return {key: var.get() for key, var in self.vars.items()}

    def var(self, key: str) -> Any:
        return self.vars[key]

    def _state(self, key: str) -> str:
        return "disabled" if key in self.cfg.env_overrides else "normal"

    def _note(self, key: str) -> str:
        return "Set by an environment variable" if key in self.cfg.env_overrides else ""

    @property
    def dirty(self) -> bool:
        return self._values() != self._snapshot

    def _changed(self, key: str) -> None:
        self._refresh_footer()
        if key == "playback.volume":
            self._apply_live_volume()
        if key == "vision.provider" and "reading" in self._pages:
            self.win.after_idle(lambda: self._rebuild("reading"))
        if key == "elevenlabs.api_key":
            self._voices, self._voice_error = None, ""
        if self._home_job is not None:
            self.win.after_cancel(self._home_job)
        self._home_job = self.win.after(200, self._refresh_home_status)

    # ---- shell ------------------------------------------------------------------------

    def _build_shell(self) -> None:
        self.win.grid_columnconfigure(1, weight=1)
        self.win.grid_rowconfigure(0, weight=1)

        sidebar = ctk.CTkFrame(self.win, fg_color=t.WINDOW_BG, corner_radius=0, width=236)
        sidebar.grid(row=0, column=0, rowspan=2, sticky="nsw")
        sidebar.grid_propagate(False)
        sidebar.grid_columnconfigure(0, weight=1)

        brand = ctk.CTkFrame(sidebar, fg_color="transparent")
        brand.grid(row=0, column=0, sticky="ew", padx=20, pady=(22, 18))
        try:
            logo = Image.open(icon_path()).convert("RGBA")
            ctk.CTkLabel(brand, text="", image=ctk.CTkImage(logo, logo, size=(30, 30))).pack(side="left", padx=(0, 10))
        except OSError:
            pass
        names = ctk.CTkFrame(brand, fg_color="transparent")
        names.pack(side="left")
        ctk.CTkLabel(names, text="SnapNarrate", font=self.fonts.body_strong, text_color=t.TEXT, anchor="w").pack(anchor="w")
        ctk.CTkLabel(names, text=f"Version {get_app_version()}", font=self.fonts.caption, text_color=t.TEXT_SECONDARY, anchor="w").pack(anchor="w")

        for index, (page_id, label, icon_name) in enumerate(PAGES, start=1):
            holder = ctk.CTkFrame(sidebar, fg_color="transparent", height=40)
            holder.grid(row=index, column=0, sticky="ew", padx=(10, 12), pady=1)
            holder.grid_columnconfigure(1, weight=1)
            bar = ctk.CTkFrame(holder, width=3, height=18, corner_radius=2, fg_color="transparent")
            bar.grid(row=0, column=0, padx=(0, 2))
            nav = ctk.CTkButton(
                holder, text=label, image=icon(icon_name), compound="left", anchor="w", height=38, corner_radius=4,
                font=self.fonts.body, fg_color="transparent", hover_color=t.NAV_HOVER, text_color=t.TEXT,
                command=lambda p=page_id: self.show(p),
            )  # fmt: skip
            nav.grid(row=0, column=1, sticky="ew")
            self._nav[page_id] = (nav, bar)

        sidebar.grid_rowconfigure(len(PAGES) + 1, weight=1)
        self._status_pill = ctk.CTkLabel(sidebar, text="", font=self.fonts.caption, text_color=t.TEXT_SECONDARY, anchor="w")
        self._status_pill.grid(row=len(PAGES) + 2, column=0, sticky="ew", padx=24, pady=(0, 18))

        content = ctk.CTkFrame(self.win, fg_color=t.WINDOW_BG, corner_radius=0)
        content.grid(row=0, column=1, sticky="nsew")
        content.grid_columnconfigure(0, weight=1)
        content.grid_rowconfigure(1, weight=1)
        self._title = ctk.CTkLabel(content, text="", font=self.fonts.title, text_color=t.TEXT, anchor="w")
        self._title.grid(row=0, column=0, sticky="ew", padx=40, pady=(26, 6))
        self._page_host = ctk.CTkFrame(content, fg_color="transparent")
        self._page_host.grid(row=1, column=0, sticky="nsew")
        self._page_host.grid_columnconfigure(0, weight=1)
        self._page_host.grid_rowconfigure(0, weight=1)

        footer = ctk.CTkFrame(self.win, fg_color=t.FOOTER_BG, corner_radius=0, height=64)
        footer.grid(row=1, column=1, sticky="ew")
        footer.grid_columnconfigure(0, weight=1)
        self._footer_msg = ctk.CTkLabel(footer, text="", font=self.fonts.body, text_color=t.TEXT_SECONDARY, anchor="w")
        self._footer_msg.grid(row=0, column=0, sticky="w", padx=40, pady=16)
        self._discard_btn = button(footer, "Discard", self.discard, self.fonts, width=110)
        self._discard_btn.grid(row=0, column=1, padx=(0, 8))
        self._save_btn = button(footer, "Save", self.save, self.fonts, accent=True, width=110)
        self._save_btn.grid(row=0, column=2, padx=(0, 40))

    def show(self, page_id: str) -> None:
        if page_id not in {p for p, _, _ in PAGES}:
            page_id = "home"
        if self._current in self._pages:
            self._pages[self._current].grid_remove()
        if page_id not in self._pages:
            self._pages[page_id] = self._build_page(page_id)
        self._pages[page_id].grid(row=0, column=0, sticky="nsew")
        self._current = page_id
        self._title.configure(text=next(label for p, label, _ in PAGES if p == page_id))
        for pid, (nav, bar) in self._nav.items():
            selected = pid == page_id
            nav.configure(fg_color=t.NAV_SELECTED if selected else "transparent", font=self.fonts.body_strong if selected else self.fonts.body)
            bar.configure(fg_color=t.ACCENT if selected else "transparent")
        if page_id == "voice" and self._voices is None and not self._voice_error and self.var("elevenlabs.api_key").get().strip():
            self._load_voices()

    def _rebuild(self, page_id: str) -> None:
        page = self._pages.pop(page_id, None)
        if page is not None:
            page.destroy()
        if self._current == page_id:
            self._current = ""
            self.show(page_id)

    def _build_page(self, page_id: str) -> ctk.CTkScrollableFrame:
        page = ctk.CTkScrollableFrame(
            self._page_host, fg_color="transparent", scrollbar_button_color=t.CONTROL_BORDER,
            scrollbar_button_hover_color=t.TEXT_SECONDARY,
        )  # fmt: skip
        body = ctk.CTkFrame(page, fg_color="transparent")
        body.pack(fill="both", expand=True, padx=(32, 24), pady=(0, 28))
        getattr(self, f"_page_{page_id}")(body)
        return page

    # ---- row helpers ------------------------------------------------------------------

    def _row(self, card: Card, key: str, title: str, description: str, build: Callable[[Any], Any]) -> Any:
        self.titles.setdefault(key, title)
        return card.add(title, description, build, note=self._note(key))

    def add_switch(self, card: Card, key: str, title: str, description: str = "") -> Any:
        return self._row(card, key, title, description, lambda p: switch(p, self.var(key), self._state(key)))

    def add_option(self, card: Card, key: str, title: str, description: str, options: Any, width: int = 280) -> Any:
        return self._row(card, key, title, description, lambda p: LabeledOption(p, self.var(key), options, self.fonts, width, self._state(key)))

    def add_segmented(self, card: Card, key: str, title: str, description: str, options: Any) -> Any:
        return self._row(card, key, title, description, lambda p: Segmented(p, self.var(key), options, self.fonts, self._state(key)))

    def add_text(
        self, card: Card, key: str, title: str, description: str = "", *, secret: bool = False,
        placeholder: str = "", unit: str = "", width: int = 280,
    ) -> Any:  # fmt: skip
        return self._row(
            card, key, title, description,
            lambda p: TextField(p, self.var(key), self.fonts, width, secret, placeholder, unit, self._state(key)),
        )  # fmt: skip

    def add_number(self, card: Card, key: str, title: str, description: str = "", unit: str = "") -> Any:
        return self.add_text(card, key, title, description, unit=unit, width=96)

    def add_slider(
        self, card: Card, key: str, title: str, description: str, low: float, high: float, step: float,
        fmt: Callable[[float], str],
    ) -> Any:  # fmt: skip
        integer = self.types[key] is int
        return self._row(
            card, key, title, description,
            lambda p: Slider(p, self.var(key), self.fonts, low, high, step, fmt, integer, self._state(key)),
        )  # fmt: skip

    def add_hotkey(self, card: Card, key: str, title: str, description: str = "") -> Any:
        def validate(spec: str) -> str | None:
            others = [self.var(k).get() for k in HOTKEY_KEYS if k != key and self.var(k).get()]
            return hotkey_problem(spec, others)

        return self._row(
            card, key, title, description,
            lambda p: HotkeyRecorder(
                p, self.var(key), self.fonts, validate, self.actions.pause_hotkeys, self._state(key),
                optional=key in OPTIONAL_HOTKEYS,
            ),
        )  # fmt: skip

    def add_link(self, card: Card, title: str, description: str, text: str, url: str) -> Any:
        return card.add(title, description, lambda p: LinkLabel(p, text, url, self.fonts))

    # ---- pages ------------------------------------------------------------------------

    def _page_home(self, body: Any) -> None:
        self._home_holder = ctk.CTkFrame(body, fg_color="transparent")
        self._home_holder.pack(fill="x", pady=(8, 0))
        self._refresh_home_status()

        card = section(body, self.fonts, "Quick settings")
        self.add_slider(card, "playback.volume", "Narration volume", "Independent of the Windows volume", 0.1, 1.5, 0.05, lambda v: f"{v:.0%}")
        self.add_segmented(card, "capture.mode", "Capture", "What the read-screen shortcut captures", CAPTURE_MODES)
        self.add_switch(card, "hud.enabled", "Subtitles over the game", "Shows the line being read, with a progress bar")
        if self.startup is not None:
            self._row(card, STARTUP_KEY, "Start with Windows", "Launch SnapNarrate when you sign in", lambda p: switch(p, self.var(STARTUP_KEY)))

    def _refresh_home_status(self) -> None:
        self._home_job = None
        cfg = self._preview_config()
        missing = missing_required(cfg)
        running = self.actions.app_running()
        self._status_pill.configure(
            text="●  Setup needed" if missing else ("●  Running" if running else "●  Not running"),
            text_color=t.WARNING if missing else (t.SUCCESS if running else t.TEXT_SECONDARY),
        )
        holder = getattr(self, "_home_holder", None)
        if holder is None or not holder.winfo_exists():
            return
        for child in holder.winfo_children():
            child.destroy()

        card = ctk.CTkFrame(holder, fg_color=t.CARD_BG, border_color=t.CARD_BORDER, border_width=1, corner_radius=8)
        card.pack(fill="x")
        card.grid_columnconfigure(1, weight=1)
        if missing:
            symbol, color = "warning", t.WARNING
            headline = "Finish setting up"
            detail = "SnapNarrate needs " + ", ".join(missing) + " before it can read."
        elif running:
            symbol, color = "check", t.SUCCESS
            headline = "Ready to read"
            detail = f"Press {' + '.join(keycaps(cfg.capture.hotkey))} in a game to read the screen aloud."
        else:
            symbol, color = "rocket", t.ACCENT
            headline = "SnapNarrate isn't running"
            detail = "Start it so your shortcuts work in games."
        ctk.CTkLabel(card, text="", image=icon(symbol, 28, color)).grid(row=0, column=0, rowspan=2, padx=(22, 16), pady=22)
        ctk.CTkLabel(card, text=headline, font=self.fonts.subtitle, text_color=t.TEXT, anchor="w").grid(row=0, column=1, sticky="sw", pady=(20, 0))
        ctk.CTkLabel(card, text=detail, font=self.fonts.body, text_color=t.TEXT_SECONDARY, anchor="w", justify="left", wraplength=460).grid(
            row=1, column=1, sticky="nw", pady=(2, 20)
        )
        actions = ctk.CTkFrame(card, fg_color="transparent")
        actions.grid(row=0, column=2, rowspan=2, padx=22)
        if missing:
            pages: list[str] = []
            for item in missing:
                page = MISSING_TO_PAGE.get(item, "home")
                if page not in pages:
                    pages.append(page)
            for index, page in enumerate(pages):
                label = "Set up voice" if page == "voice" else "Set up reading"
                button(actions, label, lambda p=page: self.show(p), self.fonts, accent=index == 0, width=150).pack(pady=3)
        elif running:
            if self.actions.test_voice:
                button(actions, "Test voice", self.actions.test_voice, self.fonts, icon=t.ICONS["play"], width=150).pack(pady=3)
            if self.actions.run_self_test:
                button(actions, "Run self-test", self.actions.run_self_test, self.fonts, width=150).pack(pady=3)
        elif self.actions.start_app:
            button(actions, "Start SnapNarrate", self._start_app, self.fonts, accent=True, width=170).pack(pady=3)

        provider = next((name for value, name, _ in PROVIDERS if value == cfg.vision.provider), cfg.vision.provider)
        model = {
            "ollama-cloud": cfg.ollama_cloud.model,
            "openai": cfg.openai.model,
            "ollama": cfg.ollama.model,
        }.get(cfg.vision.provider, "")
        voice = cfg.elevenlabs.voice_name or ("Not chosen" if not cfg.elevenlabs.voice_id else "Selected voice")
        summary = ctk.CTkFrame(holder, fg_color="transparent")
        summary.pack(fill="x", pady=(10, 0), padx=4)
        for label, value in (("Voice", voice), ("Reading", f"{provider} · {model}" if model else provider)):
            ctk.CTkLabel(summary, text=f"{label}:", font=self.fonts.caption, text_color=t.TEXT_SECONDARY).pack(side="left")
            ctk.CTkLabel(summary, text=value, font=self.fonts.caption, text_color=t.TEXT).pack(side="left", padx=(4, 22))

    def _start_app(self) -> None:
        if self.dirty and not self.save():
            return
        if self.actions.start_app:
            self.actions.start_app()
            self.flash("Starting SnapNarrate…")
            self.win.after(2500, self._refresh_home_status)

    def _page_voice(self, body: Any) -> None:
        card = section(body, self.fonts, "ElevenLabs account")
        self.add_text(card, "elevenlabs.api_key", "API key", "Starts with sk_", secret=True, width=320)
        self.add_link(card, "Need a key?", "Create one in your ElevenLabs account settings", "Get an API key", "https://elevenlabs.io/app/settings/api-keys")

        ctk.CTkLabel(body, text="Voice", font=self.fonts.body_strong, text_color=t.TEXT, anchor="w").pack(fill="x", padx=4, pady=(18, 6))
        self._voice_panel = VoicePicker(body, self)
        self._voice_panel.pack(fill="x")

        card = section(body, self.fonts, "Sound")
        self.add_slider(card, "playback.volume", "Narration volume", "Independent of the Windows volume", 0.1, 1.5, 0.05, lambda v: f"{v:.0%}")
        self.add_option(card, "elevenlabs.model_id", "Voice model", "Quality and speed trade-off", VOICE_MODELS)
        self.add_option(card, "elevenlabs.speech_fast_model_id", "First sentence", "A faster model here makes speech start sooner", FIRST_CHUNK_MODELS)
        self.add_option(card, "elevenlabs.output_format", "Audio format", "", AUDIO_FORMATS)
        card.add("Hear it with your settings", "Speaks a sample line (uses a few ElevenLabs characters)",
                 lambda p: button(p, "Play sample", self._speak_sample, self.fonts, icon=t.ICONS["play"], width=140))  # fmt: skip

    def _page_reading(self, body: Any) -> None:
        ctk.CTkLabel(body, text="Service that reads your screen", font=self.fonts.body_strong, text_color=t.TEXT, anchor="w").pack(
            fill="x", padx=4, pady=(8, 6)
        )
        card = Card(body, self.fonts)
        card.pack(fill="x")
        provider_var = self.var("vision.provider")
        choices = list(PROVIDERS)
        if provider_var.get() not in {value for value, _, _ in choices}:
            choices.append((provider_var.get(), provider_var.get(), "Provided by an addon"))
        for value, label, description in choices:
            card.add_full(lambda p, v=value, l=label, d=description: self._provider_choice(p, v, l, d))

        provider = provider_var.get()
        if provider == "ollama-cloud":
            card = section(body, self.fonts, "Ollama Cloud")
            self.add_text(card, "ollama_cloud.api_key", "API key", "", secret=True, width=320)
            self.add_link(card, "Need a key?", "Add pay-as-you-go credit, then create a key", "Get an API key", "https://ollama.com/settings/keys")
            self.add_option(card, "ollama_cloud.model", "Model", "All of these can read images", CLOUD_MODELS)
        elif provider == "openai":
            card = section(body, self.fonts, "OpenAI")
            self.add_text(card, "openai.api_key", "API key", "", secret=True, width=320)
            self.add_text(card, "openai.model", "Model", "Must support images")
            self.add_text(card, "openai.base_url", "Server", "Any OpenAI-compatible endpoint")
        elif provider == "ollama":
            card = section(body, self.fonts, "Ollama on this PC")
            self.add_text(card, "ollama.base_url", "Server", "Where Ollama is listening")
            self.add_text(card, "ollama.model", "Model", "Must support images, e.g. qwen2.5vl:7b")

        card = section(body, self.fonts, "Speed")
        self.add_switch(card, "playback.speech_first_enabled", "Start speaking right away", "Reads the first lines aloud while the rest of the screen is still being read")
        self.add_switch(card, "vision.ultra_fast_mode", "Quick first read", "Ask for just the opening paragraph first")
        self.add_switch(card, "vision.fast_mode", "Fast full read", "Faster, occasionally misses a paragraph")
        self.add_number(card, "vision.timeout_sec", "Give up after", "", unit="seconds")

        card = section(body, self.fonts, "What to read")
        self.add_switch(card, "dedup.enabled", "Skip text I just heard", "Pressing the shortcut twice on the same screen won't repeat it")

    def _provider_choice(self, parent: Any, value: str, label: str, description: str) -> Any:
        row = ctk.CTkFrame(parent, fg_color="transparent")
        radio = ctk.CTkRadioButton(
            row, text=label, value=value, variable=self.var("vision.provider"), font=self.fonts.body,
            text_color=t.TEXT, fg_color=t.ACCENT, hover_color=t.ACCENT_HOVER, state=self._state("vision.provider"),
        )  # fmt: skip
        radio.pack(anchor="w")
        ctk.CTkLabel(row, text=description, font=self.fonts.caption, text_color=t.TEXT_SECONDARY, anchor="w").pack(anchor="w", padx=(30, 0))
        return row

    def _page_hotkeys(self, body: Any) -> None:
        card = section(body, self.fonts, "Shortcuts")
        self.add_hotkey(card, "capture.hotkey", "Read the screen", "Uses the capture setting below")
        self.add_hotkey(card, "capture.region_hotkey", "Read a region", "Drag a box around the text")
        self.add_hotkey(card, "capture.stop_hotkey", "Stop speaking")
        self.add_hotkey(card, "capture.volume_up_hotkey", "Narration louder", "Optional · 10% per press")
        self.add_hotkey(card, "capture.volume_down_hotkey", "Narration quieter", "Optional · 10% per press")

        card = section(body, self.fonts, "Capture")
        self.add_segmented(card, "capture.mode", "Read-screen shortcut captures", "", CAPTURE_MODES)

        def sound_control(parent: Any) -> Any:
            frame = ctk.CTkFrame(parent, fg_color="transparent")
            LabeledOption(frame, self.var("capture.sound_name"), SOUNDS, self.fonts, 220).pack(side="left")
            button(frame, "", self._play_capture_sound, self.fonts, icon=t.ICONS["play"]).pack(side="left", padx=(6, 0))
            return frame

        self._row(card, "capture.sound_name", "Capture sound", "Plays when the screen is captured", sound_control)
        self.add_number(card, "capture.cooldown_ms", "Minimum time between captures", "", unit="ms")
        self.add_number(card, "capture.min_region_px", "Smallest region", "", unit="px")

        card = section(body, self.fonts, "Image sent for reading")
        self.add_number(card, "capture.max_dimension", "Longest side", "Smaller is faster and cheaper · 0 sends full size", unit="px")
        self.add_segmented(card, "capture.image_format", "Format", "", [("jpeg", "JPEG"), ("png", "PNG")])
        self.add_slider(card, "capture.jpeg_quality", "JPEG quality", "", 40, 100, 5, lambda v: f"{v:.0f}")

    def _page_overlay(self, body: Any) -> None:
        card = section(body, self.fonts, "Subtitles")
        self.add_switch(card, "hud.enabled", "Show subtitles over the game", "Works with games in borderless or windowed mode")
        self.add_switch(card, "hud.progress_bar", "Progress bar", "One segment per spoken chunk")
        self.add_segmented(card, "hud.position", "Position", "", [("bottom", "Bottom"), ("top", "Top")])
        self.add_slider(card, "hud.font_size", "Text size", "", 12, 48, 1, lambda v: f"{v:.0f} pt")
        self.add_slider(card, "hud.opacity", "Background opacity", "", 0.2, 1.0, 0.05, lambda v: f"{v:.0%}")
        self.add_slider(card, "hud.linger_ms", "Keep visible after speaking", "", 0, 5000, 250, lambda v: f"{v / 1000:.1f} s")

        card = section(body, self.fonts, "Integrations")
        self.add_switch(card, "api.enabled", "Local control API", "Lets widgets and tools on this PC control SnapNarrate")
        self.add_number(card, "api.port", "Port", "Only reachable from this PC")
        card.add("Access token", "Tools must send this with every request",
                 lambda p: button(p, "Copy token", self._copy_token, self.fonts, icon=t.ICONS["copy"], width=140))  # fmt: skip
        self.add_link(card, "Build your own", "Endpoints and events for widgets and scripts", "Read the guide", "https://github.com/schmidbr/snapnarrate/blob/main/docs/ADDONS.md")

    def _page_advanced(self, body: Any) -> None:
        card = section(body, self.fonts, "Text filters")
        self.add_number(card, "filter.min_block_chars", "Ignore text shorter than", "", unit="characters")
        self.add_number(card, "filter.ignore_short_lines", "Ignore lines shorter than", "Unless part of a paragraph", unit="words")
        self.add_slider(card, "dedup.similarity_threshold", "Repeat detection", "How similar text must be to count as already read", 0.5, 1.0, 0.01, lambda v: f"{v:.0%}")

        card = section(body, self.fonts, "Speech")
        self.add_number(card, "playback.initial_chunk_chars", "First chunk", "Shorter starts speaking sooner", unit="characters")
        self.add_number(card, "playback.followup_chunk_chars", "Later chunks", "", unit="characters")
        self.add_number(card, "playback.followup_min_chars", "Shortest standalone chunk", "Shorter pieces join the chunk before", unit="characters")
        self.add_number(card, "playback.retry_count", "Retries when a voice request fails", "")
        self.add_number(card, "playback.retry_backoff_ms", "Wait before retrying", "", unit="ms")

        card = section(body, self.fonts, "First-read models")
        self.add_text(card, "ollama_cloud.ultra_fast_model", "Ollama Cloud", "Optional faster model for the quick first read", placeholder="Same as main model")
        self.add_text(card, "openai.ultra_fast_model", "OpenAI", "", placeholder="Same as main model")
        self.add_text(card, "ollama.ultra_fast_model", "Ollama on this PC", "", placeholder="Same as main model")

        card = section(body, self.fonts, "Ollama tuning")
        self.add_text(card, "ollama.keep_alive", "Keep model loaded", "Local Ollama only", width=96)
        self.add_number(card, "ollama.num_predict", "Max output tokens", "")
        self.add_number(card, "ollama.temperature", "Temperature", "")
        self.add_number(card, "ollama.top_p", "Top p", "")
        self.add_number(card, "ollama.min_paragraphs", "Expected paragraphs", "Fewer triggers a stricter retry")
        self.add_number(card, "ollama.coverage_retry_attempts", "Coverage retries", "")

        card = section(body, self.fonts, "OpenAI usage report")
        self.add_text(card, "openai.admin_api_key", "Admin key", "Needed for organization usage and cost", secret=True, width=320)
        self.add_number(card, "usage.openai_monthly_budget_usd", "Monthly budget", "", unit="USD")

        card = section(body, self.fonts, "Diagnostics")
        self.add_switch(card, "debug.save_screenshots", "Save captured screenshots", "Stored in the folder below")
        self.add_text(card, "debug.screenshot_dir", "Screenshot folder", "Relative to the config folder")
        self.add_text(card, "log_file", "Log file", "Relative to the config folder")

    def _page_about(self, body: Any) -> None:
        hero = ctk.CTkFrame(body, fg_color="transparent")
        hero.pack(fill="x", pady=(8, 4))
        try:
            logo = Image.open(icon_path()).convert("RGBA")
            ctk.CTkLabel(hero, text="", image=ctk.CTkImage(logo, logo, size=(56, 56))).pack(side="left", padx=(4, 16))
        except OSError:
            pass
        text = ctk.CTkFrame(hero, fg_color="transparent")
        text.pack(side="left")
        ctk.CTkLabel(text, text="SnapNarrate", font=self.fonts.subtitle, text_color=t.TEXT, anchor="w").pack(anchor="w")
        ctk.CTkLabel(text, text=f"Version {get_app_version()}", font=self.fonts.body, text_color=t.TEXT_SECONDARY, anchor="w").pack(anchor="w")
        ctk.CTkLabel(
            body, text="Reads on-screen game text aloud, so you can keep playing instead of stopping to read.",
            font=self.fonts.body, text_color=t.TEXT_SECONDARY, anchor="w",
        ).pack(fill="x", padx=4, pady=(6, 0))  # fmt: skip

        card = section(body, self.fonts, "Files")
        config_dir = self.store.path.parent
        card.add("Settings", str(self.store.path), lambda p: button(p, "Open folder", lambda: _open(config_dir), self.fonts, icon=t.ICONS["folder"], width=140))
        log_path = self.cfg.log_path
        card.add("Logs", str(log_path), lambda p: button(p, "Open folder", lambda: _open(log_path.parent), self.fonts, icon=t.ICONS["folder"], width=140))

        card = section(body, self.fonts, "Help")
        self.add_link(card, "Documentation", "Setup, command line, and troubleshooting", "Open", "https://github.com/schmidbr/snapnarrate#readme")
        self.add_link(card, "Report a problem", "Include the log file if you can", "Open issues", "https://github.com/schmidbr/snapnarrate/issues")

    # ---- actions ----------------------------------------------------------------------

    def _speech_client(self) -> Any:
        from snap_narrate.providers.elevenlabs import ElevenLabsSpeech

        return ElevenLabsSpeech(
            api_key=self.var("elevenlabs.api_key").get().strip(),
            voice_id=self.var("elevenlabs.voice_id").get().strip(),
            model_id=self.var("elevenlabs.model_id").get().strip(),
            output_format=self.var("elevenlabs.output_format").get().strip(),
            timeout_sec=30,
        )

    def _load_voices(self) -> None:
        self._voice_error = ""
        self._voices = []  # empty list = loading
        panel = getattr(self, "_voice_panel", None)
        if panel is not None and panel.winfo_exists():
            panel.set_loading()
        source = self._voice_source or (lambda _key: self._speech_client().voices())
        key = self.var("elevenlabs.api_key").get().strip()

        def done(result: Any) -> None:
            if isinstance(result, Exception):
                self._voices, self._voice_error = None, str(result)
            else:
                self._voices = list(result)
                self._voice_error = "" if self._voices else "No voices found for this account"
                if not self._voices:
                    self._voices = None
            if panel is not None and panel.winfo_exists():
                panel.render()

        run_in_background(self.post, lambda: source(key), done)

    def _player(self, output_format: str) -> Any:
        from snap_narrate.audio import AudioPlayer

        if self._preview_player is None:
            self._preview_player = AudioPlayer(output_format, on_idle=lambda: self.post(self._preview_finished))
        self._preview_player.output_format = output_format
        self._preview_player.volume = self._float("playback.volume", 1.0)
        return self._preview_player

    def play_voice_sample(self, voice: Any, done: Callable[[str | None], None]) -> None:
        """Play a voice's free sample clip. done(error or None) runs on the UI thread."""
        client = self._speech_client()

        def finished(result: Any) -> None:
            if isinstance(result, Exception):
                done(str(result))
                return
            try:
                self._player("mp3_44100_128").play(result, session=_next_preview_session())
                done(None)
            except Exception as exc:  # noqa: BLE001
                done(str(exc))

        run_in_background(self.post, lambda: client.fetch_preview(voice), finished)

    def stop_preview(self) -> None:
        if self._preview_player is not None:
            self._preview_player.stop()

    def _preview_finished(self) -> None:
        panel = getattr(self, "_voice_panel", None)
        if panel is not None and panel.winfo_exists() and panel._playing is not None:
            panel._playing = None
            panel.render()

    def _speak_sample(self) -> None:
        client = self._speech_client()
        self.flash("Generating sample…")

        def finished(result: Any) -> None:
            if isinstance(result, Exception):
                self.flash(f"Sample failed: {result}", error=True)
                return
            self._player(client.output_format).play(result, session=_next_preview_session())
            self.flash("Playing sample")

        run_in_background(self.post, lambda: client.synthesize(PREVIEW_TEXT), finished)

    def _play_capture_sound(self) -> None:
        from snap_narrate.windows import play_capture_sound

        play_capture_sound(self.var("capture.sound_name").get())

    def _copy_token(self) -> None:
        from snap_narrate.addons.api import load_or_create_token

        self.win.clipboard_clear()
        self.win.clipboard_append(load_or_create_token(user_data_dir()))
        self.flash("Access token copied")

    def _float(self, key: str, default: float) -> float:
        try:
            return float(self.var(key).get())
        except (ValueError, tk.TclError):
            return default

    def _apply_live_volume(self) -> None:
        volume = self._float("playback.volume", 1.0)
        if self._preview_player is not None:
            self._preview_player.volume = volume
        if self.actions.set_volume:
            self.actions.set_volume(volume)

    # ---- save / discard / close -------------------------------------------------------

    def _preview_config(self) -> AppConfig:
        """The config as the form currently describes it, ignoring invalid fields."""
        cfg = self.store.load()
        for key, hint in self.types.items():
            if key in cfg.env_overrides:
                continue
            try:
                cfg.set(key, coerce(self.var(key).get(), hint))
            except (TypeError, ValueError, tk.TclError):
                continue
        return cfg

    def collect(self) -> AppConfig:
        """The config to save. Raises ValueError listing every problem."""
        cfg = self.store.load()
        errors: list[str] = []
        for key, hint in self.types.items():
            if key in cfg.env_overrides:
                continue
            raw = self.var(key).get()
            try:
                cfg.set(key, coerce(raw.strip() if isinstance(raw, str) else raw, hint))
            except (TypeError, ValueError) as exc:
                errors.append(f"{self.titles.get(key, friendly(key))}: {exc}")
        chosen = [cfg.get(k) for k in HOTKEY_KEYS]
        for key, spec in zip(HOTKEY_KEYS, chosen):
            if not spec:
                if key not in OPTIONAL_HOTKEYS:
                    errors.append(f"{self.titles.get(key, friendly(key))}: choose a shortcut")
                continue
            others = [other for other_key, other in zip(HOTKEY_KEYS, chosen) if other_key != key and other]
            problem = hotkey_problem(spec, others)
            if problem:
                errors.append(f"{self.titles.get(key, friendly(key))}: {problem}")
        if errors:
            raise ValueError("\n".join(dict.fromkeys(errors)))
        return cfg

    def save(self) -> bool:
        try:
            cfg = self.collect()
            self.store.save(cfg)
            cfg = self.store.load()
            startup_wanted = bool(self.var(STARTUP_KEY).get())
            if self.startup is not None and startup_wanted != self._snapshot.get(STARTUP_KEY):
                self.startup.set(startup_wanted)
        except ValueError as exc:
            messagebox.showerror("Some settings need attention", str(exc), parent=self.win)
            return False
        except Exception as exc:  # noqa: BLE001
            logger.exception("event=settings_save_failed")
            messagebox.showerror("Could not save settings", str(exc), parent=self.win)
            return False
        for warning in cfg.warnings:
            logger.warning("event=config_warning %s", warning)
        self.cfg = cfg
        self._snapshot = self._values()
        self._refresh_footer()
        self.flash("Settings saved", success=True)
        if self.on_saved is not None:
            self.on_saved(cfg)
        return True

    def discard(self) -> None:
        for key, value in self._snapshot.items():
            if self.vars[key].get() != value:
                self.vars[key].set(value)
        self.flash("Changes discarded")

    def flash(self, message: str, success: bool = False, error: bool = False) -> None:
        color = t.DANGER if error else (t.SUCCESS if success else t.TEXT)
        self._footer_msg.configure(text=message, text_color=color)
        if self._flash_job is not None:
            self.win.after_cancel(self._flash_job)
        self._flash_job = self.win.after(3000, self._refresh_footer)

    def _refresh_footer(self) -> None:
        self._flash_job = None
        dirty = self.dirty
        self._footer_msg.configure(
            text="●  Unsaved changes" if dirty else "All changes saved",
            text_color=t.WARNING if dirty else t.TEXT_SECONDARY,
        )
        self._save_btn.configure(
            state="normal" if dirty else "disabled",
            fg_color=t.ACCENT if dirty else t.DISABLED_BG,
            text_color_disabled=t.TEXT_SECONDARY,
        )
        self._discard_btn.configure(state="normal" if dirty else "disabled", text_color_disabled=t.TEXT_SECONDARY)

    def close(self) -> None:
        if self.dirty:
            answer = messagebox.askyesnocancel("Save changes?", "You have unsaved changes. Save them before closing?", parent=self.win)
            if answer is None:
                return
            if answer and not self.save():
                return
            if not answer and self.actions.set_volume:
                try:
                    self.actions.set_volume(float(self._snapshot.get("playback.volume") or 1.0))
                except ValueError:
                    pass
        self._closed = True
        if self._preview_player is not None:
            self._preview_player.close()
        self.win.destroy()
        if self.on_closed is not None:
            self.on_closed()


_preview_sessions = iter(range(1, 1 << 30))


def _next_preview_session() -> int:
    return next(_preview_sessions)


def _open(path: Path) -> None:
    from snap_narrate.windows import open_path

    path.mkdir(parents=True, exist_ok=True)
    open_path(path)


class VoicePicker(ctk.CTkFrame):
    """Searchable list of the account's voices by name, with free sample playback."""

    def __init__(self, parent: Any, window: SettingsWindow) -> None:
        super().__init__(parent, fg_color=t.CARD_BG, border_color=t.CARD_BORDER, border_width=1, corner_radius=8)
        self.window = window
        self.fonts = window.fonts
        self._playing: str | None = None

        top = ctk.CTkFrame(self, fg_color="transparent")
        top.pack(fill="x", padx=16, pady=(14, 8))
        self._search = ctk.CTkEntry(
            top, placeholder_text="Search by name, accent or style", width=300, font=self.fonts.body,
            fg_color=t.CONTROL_BG, border_color=t.CONTROL_BORDER, border_width=1, corner_radius=4, text_color=t.TEXT,
        )  # fmt: skip
        self._search.pack(side="left")
        self._search.bind("<KeyRelease>", lambda _e: self.render())
        button(top, "Reload", window._load_voices, self.fonts, icon=t.ICONS["refresh"], width=100).pack(side="left", padx=(8, 0))
        self._status = ctk.CTkLabel(top, text="", font=self.fonts.caption, text_color=t.TEXT_SECONDARY, anchor="e")
        self._status.pack(side="right")

        self._list = ctk.CTkScrollableFrame(
            self, fg_color="transparent", height=300, scrollbar_button_color=t.CONTROL_BORDER,
            scrollbar_button_hover_color=t.TEXT_SECONDARY,
        )  # fmt: skip
        self._list.pack(fill="x", padx=8, pady=(0, 10))
        window.var("elevenlabs.voice_id").trace_add("write", lambda *_: self.after_idle(self.render))
        self.render()

    def set_loading(self) -> None:
        self._status.configure(text="Loading voices…", text_color=t.TEXT_SECONDARY)
        for child in self._list.winfo_children():
            child.destroy()

    def render(self) -> None:
        if not self.winfo_exists():
            return
        for child in self._list.winfo_children():
            child.destroy()
        window = self.window
        selected = window.var("elevenlabs.voice_id").get()
        if window._voices is None:
            if window._voice_error:
                self._status.configure(text="Couldn't load voices", text_color=t.DANGER)
                self._message(window._voice_error)
            elif not window.var("elevenlabs.api_key").get().strip():
                self._status.configure(text="", text_color=t.TEXT_SECONDARY)
                self._message("Add your ElevenLabs API key above to see your voices.")
            else:
                self._status.configure(text="", text_color=t.TEXT_SECONDARY)
                current = window.var("elevenlabs.voice_name").get() or selected
                self._message(f"Current voice: {current}. Select Reload to browse voices." if current else "Select Reload to browse voices.")
            return
        if not window._voices:
            self._status.configure(text="Loading voices…", text_color=t.TEXT_SECONDARY)
            return
        query = self._search.get().strip().lower()
        voices = [v for v in window._voices if not query or query in v.name.lower() or query in v.details.lower()]
        if self._playing is None:
            self._status.configure(text=f"{len(voices)} of {len(window._voices)} voices", text_color=t.TEXT_SECONDARY)
        for voice in voices:
            self._row(voice, voice.voice_id == selected)
        if not voices:
            self._message("No voices match your search.")

    def _message(self, text: str) -> None:
        ctk.CTkLabel(self._list, text=text, font=self.fonts.body, text_color=t.TEXT_SECONDARY, anchor="w", justify="left").pack(
            fill="x", padx=8, pady=12
        )

    def _row(self, voice: Any, selected: bool) -> None:
        row = ctk.CTkFrame(self._list, fg_color=t.NAV_SELECTED if selected else "transparent", corner_radius=6)
        row.pack(fill="x", pady=1)
        row.grid_columnconfigure(1, weight=1)
        mark = ctk.CTkLabel(row, text="", width=24, image=icon("check", 14, t.ACCENT) if selected else None)
        mark.grid(row=0, column=0, rowspan=2, padx=(8, 4))
        name = ctk.CTkLabel(
            row, text=voice.name, font=self.fonts.body_strong if selected else self.fonts.body, text_color=t.TEXT, anchor="w", height=22
        )
        name.grid(row=0, column=1, sticky="w", pady=(8, 0))
        details = ctk.CTkLabel(row, text=voice.details or " ", font=self.fonts.caption, text_color=t.TEXT_SECONDARY, anchor="w", height=18)
        details.grid(row=1, column=1, sticky="w", pady=(0, 8))
        playing = self._playing == voice.voice_id
        play = button(row, "", lambda v=voice: self._toggle_sample(v), self.fonts, icon=t.ICONS["stop" if playing else "play"])
        play.configure(font=self.fonts.icon_small, fg_color="transparent", border_width=0, state="normal" if voice.preview_url else "disabled")
        play.grid(row=0, column=2, rowspan=2, padx=8)
        for widget in (row, mark, name, details):
            widget.bind("<Button-1>", lambda _e, v=voice: self._choose(v))
            widget.bind("<Enter>", lambda _e, r=row, s=selected: r.configure(fg_color=t.NAV_SELECTED if s else t.NAV_HOVER))
            widget.bind("<Leave>", lambda _e, r=row, s=selected: r.configure(fg_color=t.NAV_SELECTED if s else "transparent"))

    def _choose(self, voice: Any) -> None:
        self.window.var("elevenlabs.voice_name").set(voice.name)
        self.window.var("elevenlabs.voice_id").set(voice.voice_id)

    def _toggle_sample(self, voice: Any) -> None:
        if self._playing == voice.voice_id:
            self.window.stop_preview()
            self._playing = None
            self.render()
            return
        self._playing = voice.voice_id
        self._status.configure(text=f"Loading {voice.name}…", text_color=t.TEXT_SECONDARY)
        self.render()

        def done(error: str | None) -> None:
            if not self.winfo_exists():
                return
            if error:
                self._playing = None
                self._status.configure(text=f"Sample failed: {error}", text_color=t.DANGER)
            else:
                self._status.configure(text=f"Playing {voice.name}", text_color=t.TEXT_SECONDARY)
            self.render()

        self.window.play_voice_sample(voice, done)


def run_standalone(store: ConfigStore, startup: object | None = None) -> int:
    """`snapnarrate ui`: the window as its own process (the tray app need not be running)."""
    from snap_narrate.windows import is_app_running, launch_command

    def start_app() -> None:
        import subprocess

        subprocess.Popen(launch_command(store.path), close_fds=True)  # noqa: S603

    root = ctk.CTk()
    root.withdraw()
    store.ensure_exists()
    SettingsWindow(root, store, startup=startup, on_closed=root.quit, actions=WindowActions(app_running=is_app_running, start_app=start_app))
    root.mainloop()
    root.destroy()
    return 0

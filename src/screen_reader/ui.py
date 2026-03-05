from __future__ import annotations

import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk

from screen_reader.config import AppConfig, init_config, load_config, save_config
from screen_reader.startup import StartupManager


class SettingsUI:
    def __init__(self, config_path: Path, startup_manager: StartupManager | None = None) -> None:
        self.config_path = config_path
        self.startup_manager = startup_manager
        if not self.config_path.exists():
            init_config(self.config_path, force=True)
        self.cfg = load_config(self.config_path)
        if self.startup_manager:
            self.cfg.app.run_at_startup = self.startup_manager.is_enabled()
        self.root = tk.Tk()
        self.root.title("Screen Reader Settings")
        self.root.geometry("800x760")
        self.root.minsize(760, 640)
        self.root.protocol("WM_DELETE_WINDOW", self._close)
        self.root.bind_all("<MouseWheel>", self._on_mousewheel)

        self.vars: dict[str, tk.Variable] = {}
        self._build()

    def _build(self) -> None:
        outer = ttk.Frame(self.root)
        outer.pack(fill=tk.BOTH, expand=True)

        self.canvas = tk.Canvas(outer, highlightthickness=0)
        scrollbar = ttk.Scrollbar(outer, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=scrollbar.set)

        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        frame = ttk.Frame(self.canvas, padding=12)
        self._canvas_window = self.canvas.create_window((0, 0), window=frame, anchor="nw")
        frame.bind("<Configure>", self._on_frame_configure)
        self.canvas.bind("<Configure>", self._on_canvas_configure)

        row = 0
        ttk.Label(frame, text="Vision Provider", font=("Segoe UI", 11, "bold")).grid(row=row, column=0, sticky="w", pady=(0, 4))
        row += 1
        self._add_combobox(frame, row, "Provider", "vision.provider", self.cfg.vision.provider, ["openai", "ollama"])
        row += 1
        self._add_entry(frame, row, "Vision Timeout (sec)", "vision.timeout_sec", str(self.cfg.vision.timeout_sec))
        row += 1

        ttk.Separator(frame).grid(row=row, column=0, columnspan=2, sticky="ew", pady=8)
        row += 1
        ttk.Label(frame, text="OpenAI", font=("Segoe UI", 11, "bold")).grid(row=row, column=0, sticky="w", pady=(0, 4))
        row += 1
        self._add_entry(frame, row, "OpenAI API Key", "openai.api_key", self.cfg.openai.api_key, show="*")
        row += 1
        self._add_entry(frame, row, "OpenAI Model", "openai.model", self.cfg.openai.model)
        row += 1
        self._add_entry(frame, row, "OpenAI Base URL", "openai.base_url", self.cfg.openai.base_url)
        row += 1

        ttk.Separator(frame).grid(row=row, column=0, columnspan=2, sticky="ew", pady=8)
        row += 1
        ttk.Label(frame, text="Ollama", font=("Segoe UI", 11, "bold")).grid(row=row, column=0, sticky="w", pady=(0, 4))
        row += 1
        self._add_entry(frame, row, "Ollama Base URL", "ollama.base_url", self.cfg.ollama.base_url)
        row += 1
        self._add_entry(frame, row, "Ollama Model", "ollama.model", self.cfg.ollama.model)
        row += 1
        self._add_entry(frame, row, "Ollama Keep Alive", "ollama.keep_alive", self.cfg.ollama.keep_alive)
        row += 1
        self._add_entry(frame, row, "Ollama Num Predict", "ollama.num_predict", str(self.cfg.ollama.num_predict))
        row += 1
        self._add_entry(frame, row, "Ollama Temperature", "ollama.temperature", str(self.cfg.ollama.temperature))
        row += 1
        self._add_entry(frame, row, "Ollama Top P", "ollama.top_p", str(self.cfg.ollama.top_p))
        row += 1
        self._add_entry(
            frame,
            row,
            "Ollama Continuation Attempts",
            "ollama.continuation_attempts",
            str(self.cfg.ollama.continuation_attempts),
        )
        row += 1
        self._add_entry(frame, row, "Ollama Min Paragraphs", "ollama.min_paragraphs", str(self.cfg.ollama.min_paragraphs))
        row += 1
        self._add_entry(
            frame,
            row,
            "Ollama Coverage Retry Attempts",
            "ollama.coverage_retry_attempts",
            str(self.cfg.ollama.coverage_retry_attempts),
        )
        row += 1

        ttk.Separator(frame).grid(row=row, column=0, columnspan=2, sticky="ew", pady=8)
        row += 1
        ttk.Label(frame, text="ElevenLabs", font=("Segoe UI", 11, "bold")).grid(row=row, column=0, sticky="w", pady=(0, 4))
        row += 1
        self._add_entry(frame, row, "ElevenLabs API Key", "elevenlabs.api_key", self.cfg.elevenlabs.api_key, show="*")
        row += 1
        self._add_entry(frame, row, "Voice ID", "elevenlabs.voice_id", self.cfg.elevenlabs.voice_id)
        row += 1
        self._add_entry(frame, row, "Model ID", "elevenlabs.model_id", self.cfg.elevenlabs.model_id)
        row += 1
        self._add_entry(frame, row, "Output Format", "elevenlabs.output_format", self.cfg.elevenlabs.output_format)
        row += 1

        ttk.Separator(frame).grid(row=row, column=0, columnspan=2, sticky="ew", pady=8)
        row += 1
        ttk.Label(frame, text="Hotkeys & Capture", font=("Segoe UI", 11, "bold")).grid(row=row, column=0, sticky="w", pady=(0, 4))
        row += 1
        self._add_entry(frame, row, "Capture Hotkey", "capture.hotkey", self.cfg.capture.hotkey)
        row += 1
        self._add_entry(frame, row, "Stop Hotkey", "capture.stop_hotkey", self.cfg.capture.stop_hotkey)
        row += 1
        self._add_entry(frame, row, "Capture Cooldown (ms)", "capture.cooldown_ms", str(self.cfg.capture.cooldown_ms))
        row += 1

        ttk.Separator(frame).grid(row=row, column=0, columnspan=2, sticky="ew", pady=8)
        row += 1
        ttk.Label(frame, text="Filtering / Dedup / Playback", font=("Segoe UI", 11, "bold")).grid(row=row, column=0, sticky="w", pady=(0, 4))
        row += 1
        self._add_entry(frame, row, "Min Block Chars", "filter.min_block_chars", str(self.cfg.filter.min_block_chars))
        row += 1
        self._add_entry(frame, row, "Ignore Short Lines (< words)", "filter.ignore_short_lines", str(self.cfg.filter.ignore_short_lines))
        row += 1
        self._add_checkbox(frame, row, "Dedup Enabled", "dedup.enabled", self.cfg.dedup.enabled)
        row += 1
        self._add_entry(frame, row, "Dedup Similarity Threshold", "dedup.similarity_threshold", str(self.cfg.dedup.similarity_threshold))
        row += 1
        self._add_entry(frame, row, "Retry Count", "playback.retry_count", str(self.cfg.playback.retry_count))
        row += 1
        self._add_entry(frame, row, "Retry Backoff (ms)", "playback.retry_backoff_ms", str(self.cfg.playback.retry_backoff_ms))
        row += 1

        ttk.Separator(frame).grid(row=row, column=0, columnspan=2, sticky="ew", pady=8)
        row += 1
        ttk.Label(frame, text="Debug / Logs", font=("Segoe UI", 11, "bold")).grid(row=row, column=0, sticky="w", pady=(0, 4))
        row += 1
        self._add_checkbox(frame, row, "Save Debug Screenshots", "debug.save_screenshots", self.cfg.debug.save_screenshots)
        row += 1
        self._add_entry(frame, row, "Debug Screenshot Directory", "debug.screenshot_dir", self.cfg.debug.screenshot_dir)
        row += 1
        self._add_entry(frame, row, "Log File", "log_file", self.cfg.log_file)
        row += 1
        self._add_checkbox(frame, row, "Run At Startup", "app.run_at_startup", self.cfg.app.run_at_startup)
        row += 1

        button_row = ttk.Frame(frame)
        button_row.grid(row=row, column=0, columnspan=2, sticky="e", pady=(10, 0))
        ttk.Button(button_row, text="Save", command=self._save).pack(side=tk.RIGHT, padx=(8, 0))
        ttk.Button(button_row, text="Save & Close", command=self._save_and_close).pack(side=tk.RIGHT)
        ttk.Button(button_row, text="Close", command=self._close).pack(side=tk.RIGHT, padx=(0, 8))

        frame.columnconfigure(1, weight=1)

    def _on_frame_configure(self, event: tk.Event) -> None:  # noqa: ARG002
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))

    def _on_canvas_configure(self, event: tk.Event) -> None:
        self.canvas.itemconfigure(self._canvas_window, width=event.width)

    def _on_mousewheel(self, event: tk.Event) -> None:
        if self.canvas.winfo_exists():
            self.canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

    def _add_entry(self, parent: ttk.Frame, row: int, label: str, key: str, value: str, show: str | None = None) -> None:
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", pady=4, padx=(0, 10))
        var = tk.StringVar(value=value)
        self.vars[key] = var
        entry = ttk.Entry(parent, textvariable=var, show=show or "")
        entry.grid(row=row, column=1, sticky="ew", pady=4)

    def _add_checkbox(self, parent: ttk.Frame, row: int, label: str, key: str, value: bool) -> None:
        var = tk.BooleanVar(value=value)
        self.vars[key] = var
        ttk.Checkbutton(parent, text=label, variable=var).grid(row=row, column=0, columnspan=2, sticky="w", pady=4)

    def _add_combobox(
        self,
        parent: ttk.Frame,
        row: int,
        label: str,
        key: str,
        value: str,
        options: list[str],
    ) -> None:
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", pady=4, padx=(0, 10))
        var = tk.StringVar(value=value if value in options else options[0])
        self.vars[key] = var
        combo = ttk.Combobox(parent, textvariable=var, values=options, state="readonly")
        combo.grid(row=row, column=1, sticky="ew", pady=4)

    def _to_int(self, key: str) -> int:
        return int(str(self.vars[key].get()).strip())

    def _to_float(self, key: str) -> float:
        return float(str(self.vars[key].get()).strip())

    def _apply_form(self, cfg: AppConfig) -> AppConfig:
        cfg.vision.provider = str(self.vars["vision.provider"].get()).strip().lower()
        cfg.vision.timeout_sec = self._to_int("vision.timeout_sec")

        cfg.openai.api_key = str(self.vars["openai.api_key"].get()).strip()
        cfg.openai.model = str(self.vars["openai.model"].get()).strip()
        cfg.openai.base_url = str(self.vars["openai.base_url"].get()).strip()

        cfg.ollama.base_url = str(self.vars["ollama.base_url"].get()).strip()
        cfg.ollama.model = str(self.vars["ollama.model"].get()).strip()
        cfg.ollama.keep_alive = str(self.vars["ollama.keep_alive"].get()).strip()
        cfg.ollama.num_predict = self._to_int("ollama.num_predict")
        cfg.ollama.temperature = self._to_float("ollama.temperature")
        cfg.ollama.top_p = self._to_float("ollama.top_p")
        cfg.ollama.continuation_attempts = self._to_int("ollama.continuation_attempts")
        cfg.ollama.min_paragraphs = self._to_int("ollama.min_paragraphs")
        cfg.ollama.coverage_retry_attempts = self._to_int("ollama.coverage_retry_attempts")

        cfg.elevenlabs.api_key = str(self.vars["elevenlabs.api_key"].get()).strip()
        cfg.elevenlabs.voice_id = str(self.vars["elevenlabs.voice_id"].get()).strip()
        cfg.elevenlabs.model_id = str(self.vars["elevenlabs.model_id"].get()).strip()
        cfg.elevenlabs.output_format = str(self.vars["elevenlabs.output_format"].get()).strip()

        cfg.capture.hotkey = str(self.vars["capture.hotkey"].get()).strip()
        cfg.capture.stop_hotkey = str(self.vars["capture.stop_hotkey"].get()).strip()
        cfg.capture.cooldown_ms = self._to_int("capture.cooldown_ms")

        cfg.filter.min_block_chars = self._to_int("filter.min_block_chars")
        cfg.filter.ignore_short_lines = self._to_int("filter.ignore_short_lines")

        cfg.dedup.enabled = bool(self.vars["dedup.enabled"].get())
        cfg.dedup.similarity_threshold = self._to_float("dedup.similarity_threshold")

        cfg.playback.retry_count = self._to_int("playback.retry_count")
        cfg.playback.retry_backoff_ms = self._to_int("playback.retry_backoff_ms")

        cfg.debug.save_screenshots = bool(self.vars["debug.save_screenshots"].get())
        cfg.debug.screenshot_dir = str(self.vars["debug.screenshot_dir"].get()).strip()
        cfg.log_file = str(self.vars["log_file"].get()).strip()
        cfg.app.run_at_startup = bool(self.vars["app.run_at_startup"].get())
        return cfg

    def _save(self) -> bool:
        try:
            updated = self._apply_form(load_config(self.config_path))
            if self.startup_manager:
                if updated.app.run_at_startup:
                    self.startup_manager.enable()
                else:
                    self.startup_manager.disable()
                updated.app.run_at_startup = self.startup_manager.is_enabled()
            save_config(self.config_path, updated)
            messagebox.showinfo("Saved", f"Settings saved to {self.config_path}")
            return True
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("Save Failed", str(exc))
            return False

    def _save_and_close(self) -> None:
        if self._save():
            self._close()

    def _close(self) -> None:
        try:
            self.root.quit()
        finally:
            self.root.destroy()

    def run(self) -> int:
        self.root.mainloop()
        return 0


def launch_settings_ui(config_path: Path) -> int:
    ui = SettingsUI(config_path)
    return ui.run()


def launch_settings_ui_with_startup(config_path: Path, startup_manager: StartupManager | None) -> int:
    ui = SettingsUI(config_path, startup_manager=startup_manager)
    return ui.run()

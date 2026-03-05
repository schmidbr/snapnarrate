from __future__ import annotations

import os
import sys
from pathlib import Path


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def executable_target() -> Path:
    return Path(sys.executable)


def appdata_config_path() -> Path:
    appdata = os.getenv("APPDATA")
    if appdata:
        return Path(appdata) / "ScreenReader" / "config.toml"
    return Path.home() / "AppData" / "Roaming" / "ScreenReader" / "config.toml"


def resolve_default_config_path() -> Path:
    exe_config = executable_target().resolve().parent / "config.toml"
    if exe_config.exists():
        return exe_config
    user_config = appdata_config_path()
    if user_config.exists():
        return user_config
    return user_config


def launch_command(config_path: Path, include_args: bool = True) -> tuple[str, str, str]:
    cfg = config_path.resolve()
    if is_frozen():
        target = str(executable_target())
        args = f'run --config "{cfg}" --game-profile default' if include_args else ""
        workdir = str(executable_target().parent)
        return target, args, workdir

    # Dev mode / non-frozen fallback.
    python_bin = str(executable_target())
    args = f'-m screen_reader run --config "{cfg}" --game-profile default' if include_args else "-m screen_reader"
    workdir = str(Path.cwd())
    return python_bin, args, workdir

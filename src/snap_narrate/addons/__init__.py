"""Addon host.

An addon is any object with `name`, `start(ctx)` and `stop()`. Built-in addons (subtitle
overlay, local API) are switched on by their config sections; third-party Python addons
are discovered through the "snapnarrate.addons" entry point group and enabled by name in
`[addons] extra`. Out-of-process integrations (a Game Bar widget, a Stream Deck plugin,
anything not written in Python) should use the local API instead. See docs/ADDONS.md.
"""

from __future__ import annotations

import importlib
import logging
from dataclasses import dataclass
from importlib.metadata import entry_points
from pathlib import Path
from typing import TYPE_CHECKING, Callable, Protocol

from snap_narrate.config import AppConfig
from snap_narrate.events import EventBus

if TYPE_CHECKING:
    from snap_narrate.engine import Engine
    from snap_narrate.history import History
    from snap_narrate.ui.tk_thread import TkThread

logger = logging.getLogger("snap_narrate")

ENTRY_POINT_GROUP = "snapnarrate.addons"


@dataclass
class AddonContext:
    engine: "Engine"
    bus: EventBus
    config: AppConfig
    ui: "TkThread | None"  # create Tk windows only through ui.submit(...)
    data_dir: Path
    history: "History | None" = None


class Addon(Protocol):
    name: str

    def start(self, ctx: AddonContext) -> None: ...

    def stop(self) -> None: ...


# name -> (module, class, is-enabled predicate)
BUILTIN: dict[str, tuple[str, str, Callable[[AppConfig], bool]]] = {
    "hud": ("snap_narrate.addons.hud", "SubtitleOverlay", lambda cfg: cfg.hud.enabled),
    "api": ("snap_narrate.addons.api", "LocalApi", lambda cfg: cfg.api.enabled),
}


def _load_builtin(name: str) -> Addon:
    module_name, class_name, _ = BUILTIN[name]
    return getattr(importlib.import_module(module_name), class_name)()


def _load_external(name: str) -> Addon:
    for ep in entry_points(group=ENTRY_POINT_GROUP):
        if ep.name == name:
            return ep.load()()
    raise LookupError(f"No installed addon named {name!r} (entry point group {ENTRY_POINT_GROUP})")


class AddonHost:
    def __init__(self, make_context: Callable[[AppConfig], AddonContext]) -> None:
        self._make_context = make_context
        self._running: list[Addon] = []

    @property
    def running(self) -> list[str]:
        return [addon.name for addon in self._running]

    def start(self, cfg: AppConfig) -> list[str]:
        """Start every enabled addon. Returns error messages for any that failed."""
        ctx = self._make_context(cfg)
        wanted: list[tuple[str, Callable[[str], Addon]]] = [
            (name, _load_builtin) for name, (_, _, enabled) in BUILTIN.items() if enabled(cfg)
        ]
        wanted += [(name, _load_external) for name in cfg.addons.extra]

        errors: list[str] = []
        for name, loader in wanted:
            try:
                addon = loader(name)
                addon.start(ctx)
                self._running.append(addon)
                logger.info("event=addon_started name=%s", name)
            except Exception as exc:  # noqa: BLE001
                logger.exception("event=addon_failed name=%s", name)
                errors.append(f"Addon {name} failed to start: {exc}")
        return errors

    def stop(self) -> None:
        for addon in reversed(self._running):
            try:
                addon.stop()
            except Exception:  # noqa: BLE001
                logger.exception("event=addon_stop_failed name=%s", addon.name)
        self._running.clear()

    def restart(self, cfg: AppConfig) -> list[str]:
        self.stop()
        return self.start(cfg)

from __future__ import annotations

from snap_narrate import __version__


def get_app_version() -> str:
    # __version__ is the single source of truth; pyproject.toml reads it at build time.
    return __version__

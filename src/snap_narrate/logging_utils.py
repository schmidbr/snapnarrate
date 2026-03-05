from __future__ import annotations

import logging
from pathlib import Path


def setup_logging(log_file: str) -> Path:
    path = Path(log_file)
    path.parent.mkdir(parents=True, exist_ok=True)

    logger = logging.getLogger("snap_narrate")
    logger.setLevel(logging.INFO)

    if not logger.handlers:
        handler = logging.FileHandler(path, encoding="utf-8")
        formatter = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
        handler.setFormatter(formatter)
        logger.addHandler(handler)

    return path


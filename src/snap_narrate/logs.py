from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path


def setup_logging(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("snap_narrate")
    logger.setLevel(logging.INFO)
    for handler in list(logger.handlers):
        if isinstance(handler, RotatingFileHandler) and Path(handler.baseFilename) == path.resolve():
            return path
        logger.removeHandler(handler)
        handler.close()
    handler = RotatingFileHandler(path, maxBytes=1_000_000, backupCount=3, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(threadName)s %(message)s"))
    logger.addHandler(handler)
    return path

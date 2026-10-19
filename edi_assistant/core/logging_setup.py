"""Rotating file logger in <data>/logs."""
from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

from . import paths

_FMT = "%(asctime)s %(levelname)s %(threadName)s %(name)s: %(message)s"


def setup_logging(level: int = logging.INFO) -> Path:
    log_path = paths.logs_dir() / "edi_assistant.log"
    root = logging.getLogger()
    for h in root.handlers:
        if getattr(h, "_edi_handler", False) and Path(h.baseFilename) == log_path:
            root.setLevel(level)
            return log_path
    h = RotatingFileHandler(log_path, maxBytes=2 * 1024 * 1024, backupCount=5, encoding="utf-8")
    h._edi_handler = True  # type: ignore[attr-defined]
    h.setFormatter(logging.Formatter(_FMT))
    root.addHandler(h)
    root.setLevel(level)
    return log_path

"""Rotating-file logging shared by the server and the regen workers."""

from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

_LOG_FORMAT = "%(asctime)s %(levelname)s [%(name)s] %(message)s"
_LOG_DATEFMT = "%Y-%m-%d %H:%M:%S"
_MAX_BYTES = 15 * 1024 * 1024
_BACKUP_COUNT = 1


def _level_from_str(name: str) -> int:
    return logging.DEBUG if name.strip().upper() == "DEBUG" else logging.INFO


def configure_logging(runtime_dir: Path, *, level: "int | None" = None) -> Path:
    """Install a rotating file handler on the root logger; returns the log
    path. Idempotent: repeated calls swap handlers rather than stacking them."""
    if level is None:
        import os
        level = _level_from_str(os.environ.get("CCD_LOG_LEVEL", "INFO"))

    runtime_dir.mkdir(parents=True, exist_ok=True)
    log_path = runtime_dir / "server.log"

    formatter = logging.Formatter(_LOG_FORMAT, datefmt=_LOG_DATEFMT)

    file_handler = RotatingFileHandler(
        log_path,
        maxBytes=_MAX_BYTES,
        backupCount=_BACKUP_COUNT,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)
    file_handler.setLevel(level)

    root = logging.getLogger()
    for h in list(root.handlers):
        root.removeHandler(h)
        try:
            h.close()
        except Exception:
            pass
    root.setLevel(level)
    root.addHandler(file_handler)

    # Under `atk start`/nohup, a stderr handler would write a second, unrotated
    # copy of every line into the redirect target.
    if sys.stderr.isatty():
        stderr_handler = logging.StreamHandler(sys.stderr)
        stderr_handler.setFormatter(formatter)
        stderr_handler.setLevel(level)
        root.addHandler(stderr_handler)

    return log_path


def get_logger(name: str) -> logging.Logger:
    """Named logger for a server module."""
    return logging.getLogger(name)


def set_log_level(level: "int | str") -> None:
    """Change the running process's log level, handlers included."""
    if isinstance(level, str):
        level = _level_from_str(level)
    root = logging.getLogger()
    root.setLevel(level)
    for handler in root.handlers:
        handler.setLevel(level)

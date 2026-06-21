"""
Logging configuration for the dashboard server + regen workers.

Single rotating log file under <plugin>/runtime/server.log. 5 MB per file,
3 backups kept (so ~20 MB max on disk). Format includes the logger name so
serve.py and regen.py traces interleave cleanly.

Call configure_logging() ONCE at process startup before any loggers are
used. It is idempotent — repeated calls swap handlers in place rather than
stacking them (matters for in-process tests and for the `python -c` smoke
checks we run during development).
"""

from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

_LOG_FORMAT = "%(asctime)s %(levelname)s [%(name)s] %(message)s"
_LOG_DATEFMT = "%Y-%m-%d %H:%M:%S"
_MAX_BYTES = 5 * 1024 * 1024
_BACKUP_COUNT = 3


def configure_logging(runtime_dir: Path, *, level: int = logging.INFO) -> Path:
    """Install a rotating file handler on the root logger (plus a console
    handler only when attached to a real terminal).

    Returns the log file path so callers can echo it at startup.
    """

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
    # Reset existing handlers so re-running this function (tests, dev reloads)
    # doesn't double-log every line.
    for h in list(root.handlers):
        root.removeHandler(h)
        try:
            h.close()
        except Exception:
            pass
    root.setLevel(level)
    root.addHandler(file_handler)

    # Console handler ONLY when attached to a real terminal (an interactive dev
    # run). Under `atk start` / nohup, stderr is redirected, so we skip it:
    # otherwise the redirect target would accumulate a second, unrotated copy of
    # every log line. The rotating file handler is the durable log.
    if sys.stderr.isatty():
        stderr_handler = logging.StreamHandler(sys.stderr)
        stderr_handler.setFormatter(formatter)
        stderr_handler.setLevel(level)
        root.addHandler(stderr_handler)

    return log_path


def get_logger(name: str) -> logging.Logger:
    """Tiny passthrough so callers don't have to import `logging` directly —
    keeps the import surface uniform across server modules."""
    return logging.getLogger(name)

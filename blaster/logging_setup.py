"""
Logging configuration: level control, quiet third-party noise, rotating app log.
"""
from __future__ import annotations

import logging
import os
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

DEFAULT_LOG_LEVEL = "INFO"
DEFAULT_LOG_DIR = Path.home() / "Library" / "Logs" / "blaster-mac-client"
LOG_FILENAME = "blaster.log"

# Keep a few rotated files so debug sessions don't fill the disk.
LOG_MAX_BYTES = 2 * 1024 * 1024  # 2 MiB
LOG_BACKUP_COUNT = 5

# Loggers that spam at INFO under normal use (HTTP status polling, BLE stack).
_NOISY_LOGGERS = (
    "aiohttp.access",
    "aiohttp.server",
    "aiohttp.web",
    "bleak",
)


def default_log_dir() -> Path:
    raw = os.environ.get("BLASTER_LOG_DIR", "").strip()
    return Path(raw) if raw else DEFAULT_LOG_DIR


def parse_log_level(value: str | None) -> int:
    """Map a level name (or None) to a logging level. Raises ValueError if invalid."""
    name = (value or os.environ.get("BLASTER_LOG_LEVEL") or DEFAULT_LOG_LEVEL).strip().upper()
    level = logging.getLevelName(name)
    if not isinstance(level, int):
        raise ValueError(f"Invalid log level {value!r}; use DEBUG, INFO, WARNING, or ERROR")
    return level


def configure_logging(
    level: str | int | None = None,
    *,
    log_dir: Path | str | None = None,
    console: bool | None = None,
) -> Path:
    """
    Configure root logging once for the process.

    - App log: rotating file at ``<log_dir>/blaster.log`` (always).
    - Console: stderr. When stderr is a TTY (interactive), mirror the chosen level;
      under launchd (non-TTY) only WARNING+ goes to stderr so StandardErrorPath stays small.
    - Third-party access/BLE loggers are raised to WARNING so status polling cannot
      fill the log.
    """
    if isinstance(level, int):
        numeric = level
    else:
        numeric = parse_log_level(level if isinstance(level, str) else None)

    directory = Path(log_dir) if log_dir is not None else default_log_dir()
    directory.mkdir(parents=True, exist_ok=True)
    log_path = directory / LOG_FILENAME

    if console is None:
        console = sys.stderr.isatty()

    root = logging.getLogger()
    root.handlers.clear()
    root.setLevel(numeric)

    formatter = logging.Formatter(
        fmt="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    file_handler = RotatingFileHandler(
        log_path,
        maxBytes=LOG_MAX_BYTES,
        backupCount=LOG_BACKUP_COUNT,
        encoding="utf-8",
    )
    file_handler.setLevel(numeric)
    file_handler.setFormatter(formatter)
    root.addHandler(file_handler)

    stream_handler = logging.StreamHandler(sys.stderr)
    stream_handler.setLevel(numeric if console else logging.WARNING)
    stream_handler.setFormatter(formatter)
    root.addHandler(stream_handler)

    for name in _NOISY_LOGGERS:
        logging.getLogger(name).setLevel(logging.WARNING)

    return log_path

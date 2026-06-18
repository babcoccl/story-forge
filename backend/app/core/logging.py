"""Structured logging configuration for StoryForge."""

import logging
import sys
from typing import Optional

from backend.app.config import settings


def setup_logging(level: Optional[str] = None) -> None:
    """Configure Python standard logging with structured format.

    Log format includes: timestamp, level, logger name, and message.
    """
    log_level = (level or settings.log_level or "INFO").upper()

    formatter = logging.Formatter(
        fmt="%(asctime)s | %(levelname)-5s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)

    root_logger = logging.getLogger()
    root_logger.setLevel(log_level)
    root_logger.handlers.clear()
    root_logger.addHandler(handler)


def get_logger(name: str) -> logging.Logger:
    """Return a named logger instance.

    Args:
        name: Typically __name__ from the calling module.

    Returns:
        Configured logging.Logger instance.
    """
    return logging.getLogger(name)
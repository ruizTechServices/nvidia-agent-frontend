"""Structured logging configuration.

Call setup_logging() once at application startup (in app.py).
Individual modules obtain their own logger via logging.getLogger(__name__).
"""

import logging
import sys


def setup_logging() -> None:
    """Configure the root logger with a structured console handler."""
    from config.settings import LOG_LEVEL

    fmt = "%(asctime)s | %(name)s | %(levelname)s | %(message)s"
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter(fmt))

    root = logging.getLogger()
    root.setLevel(getattr(logging, LOG_LEVEL.upper(), logging.DEBUG))
    root.addHandler(handler)

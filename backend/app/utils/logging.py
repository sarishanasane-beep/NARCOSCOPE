"""Structured application logging.

Technical details are logged server-side. Secrets (API keys, credentials)
are never logged.
"""

from __future__ import annotations

import logging
import sys
from typing import Any

_FORMAT = "%(asctime)s | %(levelname)-7s | %(name)s | %(message)s"


def setup_logging(level: str = "INFO") -> None:
    root = logging.getLogger()
    root.setLevel(getattr(logging, level.upper(), logging.INFO))
    if not root.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(logging.Formatter(_FORMAT))
        root.addHandler(handler)
    root.propagate = False


def log_event(logger: logging.Logger, event: str, **fields: Any) -> None:
    """Log an event as ``event key=value key=value``.

    ``None`` values are omitted so log lines stay readable.
    """
    detail = " ".join(f"{key}={value}" for key, value in fields.items() if value is not None)
    if detail:
        logger.info("%s %s", event, detail)
    else:
        logger.info("%s", event)

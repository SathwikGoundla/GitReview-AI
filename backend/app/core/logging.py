"""
GitReview AI — Structured Logging

LLD Part A.22: The Logging/Observability Module strips any field resembling
raw diff or source content before writing. Only structural metadata is logged.
"""

from __future__ import annotations

import logging
import re
import sys
from typing import Any

# Patterns that indicate a field might contain raw source / diff content.
# These are scrubbed from log records before writing.
_SENSITIVE_FIELD_PATTERNS = re.compile(
    r"(diff|patch|content|source|raw|body|text|code|file_content)",
    re.IGNORECASE,
)


def _scrub_record(record: dict[str, Any]) -> dict[str, Any]:
    """Remove any key whose name looks like it could contain raw code/diff."""
    return {k: v for k, v in record.items() if not _SENSITIVE_FIELD_PATTERNS.search(k)}


def get_logger(name: str) -> logging.Logger:
    logger = logging.getLogger(name)
    if not logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(
            logging.Formatter(
                fmt="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
                datefmt="%Y-%m-%dT%H:%M:%S",
            )
        )
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
    return logger


def log_event(logger: logging.Logger, event_type: str, context: dict[str, Any]) -> None:
    """Log a structured event. Scrubs any field that looks like raw code/diff."""
    safe_context = _scrub_record(context)
    logger.info("event=%s %s", event_type, safe_context)

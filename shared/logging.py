"""Strukturalne logowanie (JSON do stderr)."""

import json
import logging
import sys
from datetime import UTC, datetime

_logger: logging.Logger | None = None


def get_logger(name: str = "screenwright") -> logging.Logger:
    global _logger
    if _logger is None:
        _logger = logging.getLogger(name)
        _logger.setLevel(logging.INFO)
        handler = logging.StreamHandler(sys.stderr)
        handler.setFormatter(logging.Formatter("%(message)s"))
        _logger.addHandler(handler)
    return _logger


def log_entry(level: int, event: str, **fields: object) -> None:
    log = get_logger()
    payload = {"event": event, "ts": datetime.now(UTC).isoformat(), **fields}
    log.log(level, json.dumps(payload, sort_keys=True, default=str))


__all__ = ["get_logger", "log_entry"]

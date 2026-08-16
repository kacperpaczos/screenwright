"""Reporter wyników (JSON file sink)."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from shared.logging import log_entry

if TYPE_CHECKING:
    from pathlib import Path


class JsonReporter:
    def __init__(self, path: Path) -> None:
        self._path = path
        self._records: list[dict[str, object]] = []

    def record(self, payload: dict[str, object]) -> None:
        self._records.append(payload)

    def flush(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(
            json.dumps(self._records, indent=2, sort_keys=True, default=str),
            encoding="utf-8",
        )
        log_entry(20, "verification.report_flushed", path=str(self._path), count=len(self._records))


__all__ = ["JsonReporter"]

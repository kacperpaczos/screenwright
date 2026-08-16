"""Hashowanie plików i bytes."""

from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING

from shared.types import Sha256

if TYPE_CHECKING:
    from pathlib import Path

_CHUNK = 65536


def sha256_bytes(data: bytes) -> Sha256:
    return Sha256(hashlib.sha256(data).hexdigest())


def sha256_file(path: Path) -> Sha256:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        while True:
            chunk = fh.read(_CHUNK)
            if not chunk:
                break
            h.update(chunk)
    return Sha256(h.hexdigest())


__all__ = ["sha256_bytes", "sha256_file"]

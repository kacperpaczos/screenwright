"""Shared kernel — typy brandowane i walidatory pydantic.

Ten moduł NIE jest domeną. Domeny importują stąd, ale shared nigdy nie importuje
z domains/.
"""

from pathlib import Path
from typing import Annotated, NewType

from pydantic import AfterValidator


def _validate_sha256(value: str) -> str:
    if len(value) != 64 or not all(c in "0123456789abcdef" for c in value):
        raise ValueError(f"sha256 must be 64 hex chars: {value!r}")
    return value


def _validate_http_url(value: str) -> str:
    if not (value.startswith("http://") or value.startswith("https://")):
        raise ValueError(f"URL must be http(s): {value!r}")
    return value


def _validate_relative(path: Path) -> Path:
    if path.is_absolute():
        raise ValueError(f"Path must be relative: {path}")
    return path


AppId = NewType("AppId", str)
ComponentId = NewType("ComponentId", str)
SnapName = NewType("SnapName", str)
PkgName = NewType("PkgName", str)


Sha256 = Annotated[str, AfterValidator(_validate_sha256)]
HttpUrl = Annotated[str, AfterValidator(_validate_http_url)]
RelativePath = Annotated[Path, AfterValidator(_validate_relative)]


def make_sha256(value: str) -> str:
    return _validate_sha256(value)


def make_http_url(value: str) -> str:
    return _validate_http_url(value)


__all__ = [
    "AppId",
    "ComponentId",
    "HttpUrl",
    "PkgName",
    "RelativePath",
    "Sha256",
    "SnapName",
    "make_http_url",
    "make_sha256",
]

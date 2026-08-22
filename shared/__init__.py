"""Shared kernel — utilities współdzielone przez wszystkie domeny."""

from shared.hashing import sha256_bytes, sha256_file
from shared.http_client import DEFAULT_USER_AGENT, SNAP_DEVICE_SERIES, HttpClient, http_session
from shared.logging import get_logger, log_entry
from shared.media import fetch_to_corpus
from shared.pydantic_utils import construct_validated, is_test_mode, strict_validate
from shared.results import Score, ScreenshotHash, VerificationResult
from shared.settings import Settings, load_settings
from shared.types import (
    AppId,
    ComponentId,
    HttpUrl,
    PkgName,
    RelativePath,
    Sha256,
    SnapName,
)

__all__ = [
    "DEFAULT_USER_AGENT",
    "SNAP_DEVICE_SERIES",
    "AppId",
    "ComponentId",
    "HttpClient",
    "HttpUrl",
    "PkgName",
    "RelativePath",
    "Score",
    "ScreenshotHash",
    "Settings",
    "Sha256",
    "SnapName",
    "VerificationResult",
    "construct_validated",
    "fetch_to_corpus",
    "get_logger",
    "http_session",
    "is_test_mode",
    "load_settings",
    "log_entry",
    "sha256_bytes",
    "sha256_file",
    "strict_validate",
]

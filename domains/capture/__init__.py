"""Domena capture — bezgłowe przechwytywanie okna."""

from domains.capture.models import (
    CaptureResult,
    CaptureSpec,
    FrameDigest,
    WindowInfo,
)
from domains.capture.run import run as capture_run

__all__ = [
    "CaptureResult",
    "CaptureSpec",
    "FrameDigest",
    "WindowInfo",
    "capture_run",
]

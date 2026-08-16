"""Modele pydantic domeny capture."""

from datetime import datetime
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field
from shared.types import Sha256

MIN_W, MIN_H = 120, 120


class CaptureSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    cmd: list[str] = Field(min_length=1)
    out: Path
    timeout: float = Field(gt=0, default=40.0)
    settle_timeout: float = Field(gt=0, default=20.0)
    min_wait: float = Field(ge=0, default=0.0)
    stable_frames: int = Field(ge=1, default=2)
    require_change: bool = False


class WindowInfo(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    win_id: int = Field(ge=0)
    width: int = Field(ge=MIN_W)
    height: int = Field(ge=MIN_H)


class FrameDigest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    sha256: Sha256
    captured_at: datetime


class CaptureResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    out: Path
    window: WindowInfo
    settled: bool
    elapsed: float
    frames_captured: int


__all__ = [
    "MIN_H",
    "MIN_W",
    "CaptureResult",
    "CaptureSpec",
    "FrameDigest",
    "WindowInfo",
]

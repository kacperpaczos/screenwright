"""Testy jednostkowe — CaptureSpec, WindowInfo, FrameDigest, CaptureResult."""

from __future__ import annotations

from pathlib import Path

import pytest
from domains.capture.models import (
    MIN_H,
    MIN_W,
    CaptureResult,
    CaptureSpec,
    FrameDigest,
    WindowInfo,
)
from pydantic import ValidationError


class TestCaptureSpec:
    def test_default(self) -> None:
        spec = CaptureSpec(cmd=["kcalc"], out=Path("kcalc.png"))
        assert spec.timeout == 40.0
        assert spec.settle_timeout == 20.0
        assert spec.stable_frames == 2

    def test_cmd_must_be_list(self) -> None:
        with pytest.raises(ValidationError):
            CaptureSpec(cmd=[], out=Path("kcalc.png"))

    def test_negative_timeout_rejected(self) -> None:
        with pytest.raises(ValidationError):
            CaptureSpec(cmd=["x"], out=Path("x.png"), timeout=-1.0)

    def test_stable_frames_min(self) -> None:
        with pytest.raises(ValidationError):
            CaptureSpec(cmd=["x"], out=Path("x.png"), stable_frames=0)

    def test_extra_forbidden(self) -> None:
        with pytest.raises(ValidationError):
            CaptureSpec.model_validate({"cmd": ["x"], "out": "x.png", "extra_field": True})


class TestWindowInfo:
    def test_minimum_size(self) -> None:
        win = WindowInfo(win_id=123, width=MIN_W, height=MIN_H)
        assert win.win_id == 123

    def test_too_small_rejected(self) -> None:
        with pytest.raises(ValidationError):
            WindowInfo(win_id=1, width=50, height=50)

    def test_frozen(self) -> None:
        win = WindowInfo(win_id=1, width=MIN_W, height=MIN_H)
        with pytest.raises(ValidationError):
            win.width = 999  # type: ignore[misc]


class TestFrameDigest:
    def test_valid(self) -> None:
        fd = FrameDigest(sha256="a" * 64, captured_at="2026-08-15T12:00:00Z")  # type: ignore[arg-type]
        assert fd.sha256 == "a" * 64


class TestCaptureResult:
    def test_construction(self) -> None:
        win = WindowInfo(win_id=1, width=200, height=200)
        result = CaptureResult(
            out=Path("x.png"),
            window=win,
            settled=True,
            elapsed=1.5,
            frames_captured=3,
        )
        assert result.settled is True
        assert result.frames_captured == 3

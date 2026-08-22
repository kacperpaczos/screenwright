"""Shared kernel — typy wyników używane przez wiele domen."""

from datetime import datetime
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, model_validator

from shared.types import Sha256


class Score(BaseModel):
    model_config = ConfigDict(extra="forbid")

    value: float = Field(ge=0.0, le=1.0)


class VerificationResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    passed: bool
    score: Score
    threshold: Score
    location: tuple[int, int] | None = None
    expected_template: Path
    actual_screenshot: Path
    notes: str | None = None

    @model_validator(mode="after")
    def _passed_iff_above_threshold(self) -> "VerificationResult":
        expected = self.score.value >= self.threshold.value
        if self.passed != expected:
            raise ValueError(
                f"passed={self.passed} inconsistent with "
                f"score={self.score.value} vs threshold={self.threshold.value}"
            )
        return self


class ScreenshotHash(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    sha256: Sha256
    captured_at: datetime


__all__ = [
    "Score",
    "ScreenshotHash",
    "VerificationResult",
]

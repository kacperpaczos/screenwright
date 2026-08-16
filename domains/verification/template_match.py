"""Template match — OpenCV + identity fallback."""

from __future__ import annotations

from typing import TYPE_CHECKING

from shared.results import Score

if TYPE_CHECKING:
    from pathlib import Path


class IdentityMatcher:
    """Test matcher: zwraca 1.0 jeśli template == actual, inaczej 0.0."""

    threshold: Score = Score(value=0.85)

    def match(self, template: Path, actual: Path) -> Score:
        if not template.exists() or not actual.exists():
            return Score(value=0.0)
        if template.read_bytes() == actual.read_bytes():
            return Score(value=1.0)
        return Score(value=0.0)


_DEFAULT_THRESHOLD = Score(value=0.85)


class OpenCVTemplateMatcher:
    """OpenCV TM_CCOEFF_NORMED matcher."""

    def __init__(self, threshold: Score | None = None) -> None:
        self.threshold = threshold if threshold is not None else _DEFAULT_THRESHOLD

    def match(self, template: Path, actual: Path) -> Score:
        if not template.exists() or not actual.exists():
            return Score(value=0.0)
        try:
            import cv2
        except ImportError:
            return Score(value=0.0)
        template_img = cv2.imread(str(template), cv2.IMREAD_GRAYSCALE)
        actual_img = cv2.imread(str(actual), cv2.IMREAD_GRAYSCALE)
        if template_img is None or actual_img is None:
            return Score(value=0.0)
        if template_img.shape[0] > actual_img.shape[0]:
            return Score(value=0.0)
        if template_img.shape[1] > actual_img.shape[1]:
            return Score(value=0.0)
        result = cv2.matchTemplate(actual_img, template_img, cv2.TM_CCOEFF_NORMED)
        _, max_val, _, _ = cv2.minMaxLoc(result)
        return Score(value=float(max_val))


__all__ = ["IdentityMatcher", "OpenCVTemplateMatcher"]

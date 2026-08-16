"""Testy jednostkowe — verification: Score, VerificationResult, IdentityMatcher."""

from __future__ import annotations

from pathlib import Path

import pytest
from domains.verification.template_match import IdentityMatcher
from pydantic import ValidationError
from shared.results import Score, VerificationResult


def _verification_result(
    *, score: float = 1.0, threshold: float = 0.85, passed: bool = True
) -> VerificationResult:
    return VerificationResult(
        passed=passed,
        score=Score(value=score),
        threshold=Score(value=threshold),
        location=(10, 20),
        expected_template=Path("/tmp/expected.png"),
        actual_screenshot=Path("/tmp/actual.png"),
    )


class TestScore:
    def test_valid(self) -> None:
        assert Score(value=0.5).value == 0.5

    @pytest.mark.parametrize("bad", [-0.1, 1.5, 2.0])
    def test_invalid_range(self, bad: float) -> None:
        with pytest.raises(ValidationError):
            Score(value=bad)


class TestVerificationResult:
    def test_passed_iff_score_above_threshold(self) -> None:
        assert _verification_result(score=0.9, threshold=0.85, passed=True).passed

    def test_inconsistent_rejected(self) -> None:
        with pytest.raises(ValidationError):
            _verification_result(score=0.5, threshold=0.85, passed=True)

    def test_equal_to_threshold_passes(self) -> None:
        assert _verification_result(score=0.85, threshold=0.85, passed=True).passed


class TestIdentityMatcher:
    def test_equal_files_score_one(self, tmp_path: Path) -> None:
        m = IdentityMatcher()
        a = tmp_path / "a.png"
        b = tmp_path / "b.png"
        a.write_bytes(b"\x89PNG fake")
        b.write_bytes(b"\x89PNG fake")
        assert m.match(a, b).value == 1.0

    def test_different_files_score_zero(self, tmp_path: Path) -> None:
        m = IdentityMatcher()
        a = tmp_path / "a.png"
        b = tmp_path / "b.png"
        a.write_bytes(b"\x00\x00")
        b.write_bytes(b"\xff\xff")
        assert m.match(a, b).value == 0.0

    def test_missing_file_zero(self, tmp_path: Path) -> None:
        m = IdentityMatcher()
        assert m.match(tmp_path / "missing.png", tmp_path / "missing.png").value == 0.0

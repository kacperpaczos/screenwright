"""Testy jednostkowe — weryfikacja wizualna (marker_fraction, scale-invariant)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from domains.verification.visual import (
    color_fraction,
    dominant_color,
    marker_fraction,
    store_shows_marker,
)
from PIL import Image

if TYPE_CHECKING:
    from pathlib import Path

CRIMSON = (198, 36, 63)


def _solid(path: Path, rgb: tuple[int, int, int], size: tuple[int, int] = (40, 30)) -> Path:
    Image.new("RGB", size, rgb).save(path)
    return path


def _half(path: Path, left: tuple[int, int, int], right: tuple[int, int, int]) -> Path:
    im = Image.new("RGB", (40, 30), left)
    for x in range(20, 40):
        for y in range(30):
            im.putpixel((x, y), right)
    im.save(path)
    return path


def test_dominant_color_of_solid_marker(tmp_path: Path) -> None:
    assert dominant_color(_solid(tmp_path / "m.png", CRIMSON)) == CRIMSON


def test_color_fraction_full_and_none(tmp_path: Path) -> None:
    assert color_fraction(_solid(tmp_path / "c.png", CRIMSON), CRIMSON) == 1.0
    assert color_fraction(_solid(tmp_path / "w.png", (255, 255, 255)), CRIMSON) == 0.0


def test_color_fraction_half(tmp_path: Path) -> None:
    frac = color_fraction(_half(tmp_path / "h.png", CRIMSON, (255, 255, 255)), CRIMSON)
    assert 0.45 <= frac <= 0.55


def test_marker_fraction_matches_marker_color(tmp_path: Path) -> None:
    marker = _solid(tmp_path / "marker.png", CRIMSON, size=(64, 48))
    # screenshot where the marker (crimson) fills ~half → store shows it
    shot = _half(tmp_path / "shot.png", CRIMSON, (240, 240, 240))
    frac = marker_fraction(shot, marker)
    assert frac > 0.4


def test_marker_fraction_low_when_absent(tmp_path: Path) -> None:
    marker = _solid(tmp_path / "marker.png", CRIMSON)
    shot = _solid(tmp_path / "shot.png", (30, 30, 30))  # dark desktop, no marker
    assert marker_fraction(shot, marker) < 0.03


def test_store_shows_marker_decision(tmp_path: Path) -> None:
    marker = _solid(tmp_path / "marker.png", CRIMSON)
    yes, frac = store_shows_marker(_solid(tmp_path / "s1.png", CRIMSON), marker, threshold=0.03)
    assert yes
    assert frac == 1.0
    no, frac2 = store_shows_marker(
        _solid(tmp_path / "s2.png", (255, 255, 255)), marker, threshold=0.03
    )
    assert not no
    assert frac2 == 0.0


def test_tolerance_absorbs_jpeg_like_noise(tmp_path: Path) -> None:
    marker = _solid(tmp_path / "marker.png", CRIMSON)
    # near-crimson (compression drift) still counts within tol
    near = _solid(tmp_path / "near.png", (205, 30, 70))
    assert marker_fraction(near, marker, tol=45) == 1.0

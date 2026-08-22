"""Weryfikacja wizualna: czy zrzut ekranu sklepu pokazuje NASZ obraz.

Zamiast template-matchu wrażliwego na skalę (sklep skaluje zrzut w karuzeli),
używamy proxy niezależnego od skali: **udział pikseli w dominującym kolorze
markera**. Marker screenwright to jednolita, wyrazista plama (crimson), więc gdy
sklep go renderuje, duża, spójna część kadru ma ten kolor; gdy pokazuje oryginał
albo broken-image — nie ma.

Zweryfikowane na żywo 2026-08-22: GNOME Software ~0.20, KDE Discover ~0.16,
oryginał/pusto ~0.0002-0.005 (`docs/override-deploy.md`).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from PIL import Image

if TYPE_CHECKING:
    from pathlib import Path


def dominant_color(image: Path) -> tuple[int, int, int]:
    """Średni (dominujący dla jednolitego markera) kolor RGB obrazu."""
    with Image.open(image) as im:
        r, g, b = im.convert("RGB").resize((1, 1)).getpixel((0, 0))
    return int(r), int(g), int(b)


def color_fraction(screenshot: Path, rgb: tuple[int, int, int], tol: int = 45) -> float:
    """Udział pikseli zrzutu w kolorze ``rgb`` (±``tol`` na kanał), w [0, 1]."""
    tr, tg, tb = rgb
    with Image.open(screenshot) as im:
        data = im.convert("RGB").tobytes()
    total = len(data) // 3
    if total == 0:
        return 0.0
    hits = sum(
        1
        for i in range(0, len(data), 3)
        if abs(data[i] - tr) <= tol
        and abs(data[i + 1] - tg) <= tol
        and abs(data[i + 2] - tb) <= tol
    )
    return round(hits / total, 4)


def marker_fraction(screenshot: Path, marker: Path, tol: int = 45) -> float:
    """Udział kadru pasujący do dominującego koloru ``marker`` — proxy „sklep
    pokazuje nasz obraz". Niezależne od skali i pozycji karuzeli."""
    return color_fraction(screenshot, dominant_color(marker), tol=tol)


def store_shows_marker(
    screenshot: Path, marker: Path, *, threshold: float = 0.03, tol: int = 45
) -> tuple[bool, float]:
    """(czy sklep renderuje nasz marker, zmierzony udział)."""
    frac = marker_fraction(screenshot, marker, tol=tol)
    return frac >= threshold, frac


__all__ = [
    "color_fraction",
    "dominant_color",
    "marker_fraction",
    "store_shows_marker",
]

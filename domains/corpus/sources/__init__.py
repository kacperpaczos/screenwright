"""Kolektory korpusu — jeden moduł na źródło."""

from domains.corpus.sources import (
    debian,
    elementary,
    fedora,
    flathub,
    mint,
    snap,
    ubuntu_dep11,
)

__all__ = ["debian", "elementary", "fedora", "flathub", "mint", "snap", "ubuntu_dep11"]

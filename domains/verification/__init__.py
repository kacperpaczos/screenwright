"""Domena verification — walidacja screenshotów przez template match."""

from domains.verification.ports import Reporter, TemplateMatcher
from domains.verification.report import JsonReporter
from domains.verification.template_match import (
    IdentityMatcher,
    OpenCVTemplateMatcher,
)
from domains.verification.visual import (
    color_fraction,
    dominant_color,
    marker_fraction,
    store_shows_marker,
)

__all__ = [
    "IdentityMatcher",
    "JsonReporter",
    "OpenCVTemplateMatcher",
    "Reporter",
    "TemplateMatcher",
    "color_fraction",
    "dominant_color",
    "marker_fraction",
    "store_shows_marker",
]

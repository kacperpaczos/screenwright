"""Domena verification — walidacja screenshotów przez template match."""

from domains.verification.ports import Reporter, TemplateMatcher
from domains.verification.report import JsonReporter
from domains.verification.template_match import (
    IdentityMatcher,
    OpenCVTemplateMatcher,
)

__all__ = [
    "IdentityMatcher",
    "JsonReporter",
    "OpenCVTemplateMatcher",
    "Reporter",
    "TemplateMatcher",
]

"""Domena override — AppStream catalogue override."""

from domains.override.catalog import build_override
from domains.override.models import OverrideResult, OverrideSpec

__all__ = ["OverrideResult", "OverrideSpec", "build_override"]

"""Domena override — AppStream catalogue override."""

from domains.override.catalog import build_override, patch_catalog
from domains.override.models import CatalogPatchResult, OverrideResult, OverrideSpec

__all__ = [
    "CatalogPatchResult",
    "OverrideResult",
    "OverrideSpec",
    "build_override",
    "patch_catalog",
]

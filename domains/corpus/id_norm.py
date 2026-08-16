"""Normalizacja AppStream component-id."""

from __future__ import annotations

from shared.types import AppId, ComponentId


def strip_desktop_suffix(value: str) -> str:
    """Usuwa sufiks `.desktop` jeśli obecny (case-sensitive)."""
    if value.endswith(".desktop"):
        return value[: -len(".desktop")]
    return value


def to_canonical(component_id: str) -> AppId:
    """Do postaci kanonicznej (bez `.desktop`)."""
    return AppId(strip_desktop_suffix(component_id))


def from_canonical(app_id: str, *, with_desktop: bool = False) -> ComponentId:
    """Z kanonicznej do konkretnej formy."""
    if with_desktop and not app_id.endswith(".desktop"):
        return ComponentId(f"{app_id}.desktop")
    return ComponentId(app_id)


__all__ = ["from_canonical", "strip_desktop_suffix", "to_canonical"]

"""Porty domeny override."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from pathlib import Path

    from shared.types import ComponentId


@runtime_checkable
class CatalogLoader(Protocol):
    def load(self, path: Path) -> bytes: ...


@runtime_checkable
class ComponentFinder(Protocol):
    def find(self, payload: bytes, component_id: ComponentId) -> bytes | None:
        """Zwraca XML samego komponentu lub None."""
        ...


__all__ = ["CatalogLoader", "ComponentFinder"]

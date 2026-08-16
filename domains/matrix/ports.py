"""Porty domeny matrix."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from pathlib import Path

    from shared.types import AppId

    from domains.matrix.models import DistroName


@runtime_checkable
class DistroBuilder(Protocol):
    """Adapter konkretnej dystrybucji (kickstart, autoinstall, preseed)."""

    name: DistroName

    def render_installer(self, out_dir: Path) -> Path: ...
    def golden_path(self, images_dir: Path) -> Path: ...


@runtime_checkable
class StoreDriver(Protocol):
    """Adapter konkretnego software centre."""

    distro: DistroName

    def commands_for(self, app: AppId) -> list[list[str]]:
        """Lista komend do wykonania przez qemu-guest-agent."""
        ...


@runtime_checkable
class ReporterSink(Protocol):
    def record(self, payload: dict[str, object]) -> None: ...


__all__ = ["DistroBuilder", "ReporterSink", "StoreDriver"]

"""Porty domeny capture (display, grab, discovery)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from pathlib import Path

    from shared.types import Sha256

    from domains.capture.models import WindowInfo


@runtime_checkable
class DisplayBackend(Protocol):
    def start(self) -> str:
        """Zwraca DISPLAY (np. ':96')."""
        ...

    def terminate(self) -> None: ...


@runtime_checkable
class WindowDiscovery(Protocol):
    def wait_for_window(self, display: str, deadline_monotonic: float) -> WindowInfo: ...


@runtime_checkable
class FrameGrabber(Protocol):
    def grab(self, win_id: int, out_path: Path, display: str) -> tuple[Path, Sha256]: ...


__all__ = ["DisplayBackend", "FrameGrabber", "WindowDiscovery"]

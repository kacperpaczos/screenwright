"""Porty domeny matrix."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from pathlib import Path

    from shared.types import AppId

    from domains.matrix.models import DistroName, DistroSpec, DomainConfig


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
class GuestShell(Protocol):
    """Wykonuje komendę w gościu **jako użytkownik sesji graficznej**.

    Zwraca stdout; niezerowy kod wyjścia to ``RuntimeError`` ze stderr w
    treści. Na żywo to SSH przez przekierowany port passt (``SshShell``) —
    ``qemu-guest-agent`` działa jako root w domenie SELinux
    ``virt_qemu_ga_t``, która nie może ani zmienić użytkownika (``runuser``,
    ``setpriv``), ani zagadać do systemd (``systemd-run``), więc z agenta nie
    da się trafić do sesji użytkownika (sprawdzone na Fedorze 44, 2026-08-22).
    """

    def run(self, command: list[str], timeout: float = 30.0) -> str: ...


@runtime_checkable
class GuestShellFactory(Protocol):
    """Buduje ``GuestShell`` dla konkretnego klona (port SSH z ``DomainConfig``, użytkownik z ``DistroSpec``)."""

    def __call__(self, domain: DomainConfig, distro: DistroSpec) -> GuestShell: ...


@runtime_checkable
class ReporterSink(Protocol):
    def record(self, payload: dict[str, object]) -> None: ...


@runtime_checkable
class StoreProxyLifecycle(Protocol):
    """Adapter cyklu życia snap-store-proxy (lub innego) — start/stop per distro.

    ``start()`` tylko odpala proces; ``wait_ready(timeout)`` blokuje, aż proxy
    faktycznie odpowiada, i zwraca ``False`` po upływie limitu (albo gdy proces
    zgasł). Runner nie bootuje VM-ki, dopóki ``wait_ready`` nie zwróci ``True``
    — inaczej pierwsze zapytanie sklepu trafia w zamknięty port i test
    przechodzi albo pada zależnie od tego, kto był szybszy.
    """

    url: str

    def start(self) -> None: ...
    def wait_ready(self, timeout: float) -> bool: ...
    def stop(self) -> None: ...


@runtime_checkable
class StoreProxyProvider(Protocol):
    """Fabryka StoreProxyLifecycle dla danej dystrybucji."""

    def __call__(self, distro: DistroSpec, apps: list[AppId]) -> StoreProxyLifecycle | None: ...


__all__ = [
    "DistroBuilder",
    "GuestShell",
    "GuestShellFactory",
    "ReporterSink",
    "StoreDriver",
    "StoreProxyLifecycle",
    "StoreProxyProvider",
]

"""Shared ports (Protokoły) dla komunikacji między domenami.

Każda domena definiuje swoje własne porty w `domains/<name>/ports.py`, ale te
protokoły są wspólne, bo są używane przez więcej niż jedną domenę.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from datetime import datetime
    from pathlib import Path

    from shared.types import AppId, HttpUrl, Sha256


@runtime_checkable
class SourceFetcher(Protocol):
    """Port do pobierania wpisów korpusu dla pojedynczej aplikacji."""

    def fetch(self, app: AppId) -> list[dict[str, object]]:
        """Zwraca listę dictów — domena corpus mapuje je na CorpusEntry."""
        ...


@runtime_checkable
class IndexStorage(Protocol):
    """Append-only magazyn wpisów korpusu."""

    def append(self, entry: dict[str, object]) -> None: ...

    def has(
        self,
        source_url: HttpUrl,
        sha256: Sha256,
        since: datetime | None = None,
    ) -> bool: ...

    def load(self) -> list[dict[str, object]]: ...


@runtime_checkable
class LibvirtBackend(Protocol):
    """Abstrakcja nad virsh/libvirt.

    Konwencje:
    - `define` / `create` przyjmują XML domeny jako string; backend sam dostarcza
      go na stdin do virsh.
    - `qemu_agent_exec` zwraca zdekodowane stdout (po base64 z `out-data`).
    - `save` / `restore` działają też dla domen transient (w przeciwieństwie do
      managedsave, które libvirt odmawia dla transient). `restore(..., xml=)`
      podaje libvirtowi własny XML zamiast tego zapisanego w pliku stanu —
      tak przywraca się maszynę na innym pliku dysku (warm cache).
    """

    def create_overlay(self, golden: Path, overlay: Path) -> None: ...
    def define(self, xml: str, name: str) -> None: ...
    def create(self, xml: str, name: str) -> None: ...
    def start(self, name: str) -> None: ...
    def destroy(self, name: str) -> None: ...
    def save(self, name: str, state_file: Path) -> None: ...
    def restore(self, state_file: Path, xml: Path | None = None) -> None: ...
    def screenshot(self, name: str, out_path: Path) -> Path: ...
    def domifaddr(self, name: str) -> str: ...
    def qemu_agent_exec(self, name: str, command: list[str], timeout: float = 30.0) -> str: ...


__all__ = [
    "IndexStorage",
    "LibvirtBackend",
    "SourceFetcher",
]

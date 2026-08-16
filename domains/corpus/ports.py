"""Porty domeny corpus — adaptery do pobierania i przechowywania."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from datetime import datetime

    from shared.types import AppId, HttpUrl, Sha256


@runtime_checkable
class CorpusSource(Protocol):
    """Adapter do konkretnego źródła (Fedora, Flathub, ...)."""

    distro: str
    kinds: tuple[str, ...]

    def fetch(self, app: AppId) -> list[dict[str, object]]:
        """Zwraca listę dictów — walidacja na granicy corpus."""
        ...


@runtime_checkable
class CorpusStorage(Protocol):
    """Magazyn korpusu (implementacja: IndexWriter)."""

    def load(self) -> list[dict[str, object]]: ...

    def append(self, entry: dict[str, object]) -> None: ...

    def flush(self) -> None: ...

    def has(
        self,
        source_url: HttpUrl,
        sha256: Sha256,
        since: datetime | None = None,
    ) -> bool: ...


__all__ = ["CorpusSource", "CorpusStorage"]

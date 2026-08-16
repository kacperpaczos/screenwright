"""Porty domeny verification."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from pathlib import Path

    from shared.results import Score


@runtime_checkable
class TemplateMatcher(Protocol):
    threshold: Score

    def match(self, template: Path, actual: Path) -> Score: ...


@runtime_checkable
class Reporter(Protocol):
    def record(self, payload: dict[str, object]) -> None: ...


__all__ = ["Reporter", "TemplateMatcher"]

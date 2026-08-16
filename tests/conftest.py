"""Współdzielone fixtures i helpery testowe."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from shared.types import AppId, HttpUrl, PkgName, Sha256


@pytest.fixture
def sample_corpus_entry() -> dict[str, object]:
    return {
        "app_id": AppId("org.kde.kcalc"),
        "distro": "fedora",
        "source": "fedora-appstream",
        "source_url": HttpUrl("https://example.com/source.png"),
        "kind": "source",
        "width": 800,
        "height": 600,
        "fetched": datetime.now(UTC).isoformat(),
        "sha256": Sha256("a" * 64),
        "file": "media/org.kde.kcalc/fedora/source/aa.png",
        "pkgname": PkgName("kcalc"),
        "notes": None,
    }


@pytest.fixture(autouse=True)
def _fast_sleep(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SCREENWRIGHT_TESTS_FAST", "1")

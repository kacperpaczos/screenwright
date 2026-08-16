"""Testy jednostkowe — CorpusEntry / CorpusIndex / id_norm / IndexWriter."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import pytest
from domains.corpus.id_norm import from_canonical, strip_desktop_suffix, to_canonical
from domains.corpus.index import IndexWriter
from domains.corpus.models import CorpusEntry, CorpusIndex
from pydantic import ValidationError
from shared.types import AppId, HttpUrl, Sha256

if TYPE_CHECKING:
    from pathlib import Path


def _entry(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "app_id": "org.kde.kcalc",
        "distro": "fedora",
        "source": "fedora-appstream",
        "source_url": "https://example.com/source.png",
        "kind": "source",
        "width": 800,
        "height": 600,
        "fetched": datetime.now(UTC).isoformat(),
        "sha256": "a" * 64,
        "file": "media/org.kde.kcalc/fedora/source/aa.png",
        "pkgname": "kcalc",
    }
    base.update(overrides)
    return base


class TestIdNorm:
    def test_strip_desktop_present(self) -> None:
        assert strip_desktop_suffix("org.kde.kcalc.desktop") == "org.kde.kcalc"

    def test_strip_desktop_absent(self) -> None:
        assert strip_desktop_suffix("org.kde.kcalc") == "org.kde.kcalc"

    def test_to_canonical(self) -> None:
        assert to_canonical("org.kde.kcalc.desktop") == "org.kde.kcalc"

    def test_from_canonical_with_desktop(self) -> None:
        assert from_canonical("org.kde.kcalc", with_desktop=True) == "org.kde.kcalc.desktop"

    def test_roundtrip(self) -> None:
        canonical = to_canonical("org.kde.kcalc.desktop")
        assert from_canonical(canonical) == "org.kde.kcalc"


class TestCorpusEntry:
    def test_valid(self) -> None:
        entry = CorpusEntry.model_validate(_entry())
        assert entry.app_id == "org.kde.kcalc"
        assert entry.distro == "fedora"

    def test_extra_forbidden(self) -> None:
        with pytest.raises(ValidationError):
            CorpusEntry.model_validate(_entry(unknown="x"))

    def test_frozen(self) -> None:
        entry = CorpusEntry.model_validate(_entry())
        with pytest.raises(ValidationError):
            entry.app_id = AppId("other")

    def test_fetched_future_rejected(self) -> None:
        future = (datetime.now(UTC) + timedelta(days=2)).isoformat()
        with pytest.raises(ValidationError):
            CorpusEntry.model_validate(_entry(fetched=future))

    def test_thumbnail_too_large_rejected(self) -> None:
        with pytest.raises(ValidationError):
            CorpusEntry.model_validate(_entry(kind="thumbnail", width=2000, height=1500))

    def test_source_too_small_rejected(self) -> None:
        with pytest.raises(ValidationError):
            CorpusEntry.model_validate(_entry(kind="source", width=50, height=50))

    def test_invalid_url_rejected(self) -> None:
        with pytest.raises(ValidationError):
            CorpusEntry.model_validate(_entry(source_url="not-a-url"))

    def test_invalid_sha_rejected(self) -> None:
        with pytest.raises(ValidationError):
            CorpusEntry.model_validate(_entry(sha256="z" * 64))

    def test_roundtrip_json(self) -> None:
        entry = CorpusEntry.model_validate(_entry())
        raw = entry.model_dump(mode="json")
        assert CorpusEntry.model_validate(raw) == entry


class TestCorpusIndex:
    def test_append_and_has(self) -> None:
        index = CorpusIndex()
        entry = CorpusEntry.model_validate(_entry())
        index.append(entry)
        assert index.has(HttpUrl("https://example.com/source.png"), Sha256("a" * 64))

    def test_has_different_hash(self) -> None:
        index = CorpusIndex()
        entry = CorpusEntry.model_validate(_entry())
        index.append(entry)
        assert not index.has(HttpUrl("https://example.com/source.png"), Sha256("b" * 64))


class TestIndexWriter:
    def test_load_empty(self, tmp_path: Path) -> None:
        writer = IndexWriter(tmp_path)
        assert writer.entries == []

    def test_append_and_flush(self, tmp_path: Path) -> None:
        writer = IndexWriter(tmp_path)
        entry = CorpusEntry.model_validate(_entry())
        writer.append(entry)
        writer.flush()
        raw = json.loads((tmp_path / "index.json").read_text())
        assert raw["schema_version"] == 1
        assert len(raw["entries"]) == 1

    def test_corrupt_recovery(self, tmp_path: Path) -> None:
        (tmp_path / "index.json").write_text("{ invalid json")
        writer = IndexWriter(tmp_path)
        assert writer.entries == []
        assert (tmp_path / "index.bak").exists()

    def test_add_media(self, tmp_path: Path) -> None:
        writer = IndexWriter(tmp_path)
        path, sha = writer.add_media("org.kde.kcalc", "fedora", "thumbnails", b"\x89PNG\r\n\x1a\n")
        assert path.startswith("media/org.kde.kcalc/fedora/thumbnails/")
        assert (tmp_path / path).exists()
        assert len(sha) == 64

    def test_add_media_idempotent(self, tmp_path: Path) -> None:
        """Ten sam bytes → ten sam hash → ten sam path (nie duplikujemy)."""
        writer = IndexWriter(tmp_path)
        body = b"\x89PNG same bytes"
        path1, sha1 = writer.add_media("org.kde.kcalc", "fedora", "thumbnails", body)
        path2, sha2 = writer.add_media("org.kde.kcalc", "fedora", "thumbnails", body)
        assert path1 == path2
        assert sha1 == sha2
        files = list((tmp_path / "media" / "org.kde.kcalc" / "fedora" / "thumbnails").iterdir())
        assert len(files) == 1

    def test_has_after_append(self, tmp_path: Path) -> None:
        """Po append wpis jest widoczny przez has() (idempotencja Indeksu)."""
        from datetime import UTC, datetime

        from shared.types import HttpUrl, Sha256

        writer = IndexWriter(tmp_path)
        entry = CorpusEntry.model_validate(_entry())
        writer.append(entry)
        writer.flush()
        url = HttpUrl("https://example.com/source.png")
        sha = Sha256("a" * 64)
        assert writer.has(url, sha, since=datetime(2020, 1, 1, tzinfo=UTC))
        assert not writer.has(url, Sha256("b" * 64))

    def test_atomic_flush(self, tmp_path: Path) -> None:
        writer = IndexWriter(tmp_path)
        writer.append(CorpusEntry.model_validate(_entry()))
        writer.flush()
        target = tmp_path / "index.json"
        assert target.exists()
        assert not (tmp_path / "index.json.bak").exists()

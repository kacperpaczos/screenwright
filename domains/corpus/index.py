"""Append-only writer korpusu (index.json)."""

import json
import os
import tempfile
from datetime import datetime
from pathlib import Path

from shared.hashing import sha256_bytes
from shared.http_client import HttpClient
from shared.logging import log_entry
from shared.types import HttpUrl, Sha256

from domains.corpus.models import CorpusEntry, CorpusIndex

INDEX_FILENAME = "index.json"


class IndexWriter:
    def __init__(self, root: Path) -> None:
        self._root = root
        self._index_path = root / INDEX_FILENAME
        self._index = self._load()

    @property
    def root(self) -> Path:
        return self._root

    @property
    def entries(self) -> list[CorpusEntry]:
        return list(self._index.entries)

    def _load(self) -> CorpusIndex:
        if not self._index_path.exists():
            return CorpusIndex()
        try:
            raw = json.loads(self._index_path.read_text(encoding="utf-8"))
            return CorpusIndex.model_validate(raw)
        except (json.JSONDecodeError, ValueError) as exc:
            backup = self._index_path.with_suffix(".bak")
            self._index_path.rename(backup)
            log_entry(20, "corpus.index.corrupt", backup=str(backup), error=str(exc))
            return CorpusIndex()

    def has(
        self,
        source_url: HttpUrl,
        sha256: Sha256,
        since: datetime | None = None,
    ) -> bool:
        return self._index.has(source_url, sha256, since)

    def append(self, entry: CorpusEntry) -> None:
        self._index.append(entry)

    def flush(self) -> None:
        self._root.mkdir(parents=True, exist_ok=True)
        payload = self._index.model_dump(mode="json")
        fd, tmp_name = tempfile.mkstemp(dir=self._root, prefix=".index.", suffix=".json.tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(payload, fh, indent=2, sort_keys=True)
            os.replace(tmp_name, self._index_path)
        except Exception:
            Path(tmp_name).unlink(missing_ok=True)
            raise

    def add_media(self, app_id: str, distro: str, source: str, body: bytes) -> tuple[str, str]:
        """Zapisz obraz do media/<app>/<distro>/<source>/<sha-prefix>.png.

        Zwraca (relative_path, sha256). Idempotentne.
        """
        sha = Sha256(sha256_bytes(body))
        target_dir = self._root / "media" / app_id / distro / source
        target_dir.mkdir(parents=True, exist_ok=True)
        target = target_dir / f"{sha[:8]}.png"
        if not target.exists():
            target.write_bytes(body)
        return str(target.relative_to(self._root)), sha

    def download(
        self,
        url: HttpUrl,
        app_id: str,
        distro: str,
        source: str,
        *,
        client: HttpClient | None = None,
    ) -> str | None:
        """Pobiera URL jeśli nie ma go w indeksie (idempotentnie).

        Zwraca relative_path do zapisanego pliku lub None przy błędzie.
        """
        c = client or HttpClient()
        try:
            r = c.get(url)
        except Exception as exc:
            log_entry(20, "corpus.download.error", url=url, error=str(exc))
            return None
        rel, _ = self.add_media(app_id, distro, source, r.content)
        return rel


__all__ = ["INDEX_FILENAME", "IndexWriter"]

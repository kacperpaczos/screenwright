"""Pobieranie mediów do korpusu — wspólna logika dla wszystkich kolektorów.

Idempotentne: ten sam URL+bytes → ten sam hash → nie powiela plików.
"""

from datetime import UTC, datetime
from pathlib import Path

from shared.hashing import sha256_bytes
from shared.http_client import HttpClient
from shared.logging import log_entry
from shared.types import Sha256


def fetch_to_corpus(
    entries: list[dict[str, object]],
    index_root: Path,
    *,
    client: HttpClient | None = None,
    skip_if_exists: bool = True,
) -> list[dict[str, object]]:
    """Pobiera bytes dla URL-i w entries; aktualizuje wpis o realne sha256 + path.

    Zwraca zaktualizowane wpisy. Idempotentne.
    """
    c = client or HttpClient()
    out: list[dict[str, object]] = []
    for entry in entries:
        url = entry.get("source_url")
        if not isinstance(url, str):
            out.append(entry)
            continue
        try:
            r = c.get(url)
            body = r.content
            sha = Sha256(sha256_bytes(body))
            target_dir = (
                index_root
                / "media"
                / str(entry["app_id"])
                / str(entry["distro"])
                / str(entry["source"])
            )
            target_dir.mkdir(parents=True, exist_ok=True)
            target = target_dir / f"{sha[:8]}.png"
            if skip_if_exists and target.exists():
                log_entry(15, "media.skip_exists", path=str(target))
            else:
                target.write_bytes(body)
            entry = dict(entry)
            entry["sha256"] = sha
            entry["file"] = str(target.relative_to(index_root))
            entry["fetched"] = datetime.now(UTC).isoformat()
        except Exception as exc:
            log_entry(20, "media.download_error", url=url, error=str(exc))
        out.append(entry)
    return out


__all__ = ["fetch_to_corpus"]

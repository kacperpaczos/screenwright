"""Kolektor Linux Mint — scraping autoindexu community.linuxmint.com.

Mapowanie component-id → pkgname przez DEP-11 join (plan §1 M2):
1. Fetch Ubuntu DEP-11 (noble/main) → tablica ID→Package
2. Fetch autoindexu community.linuxmint.com → tablica PNG names
3. Dla danego app_id: znajdź wpis DEP-11 z Package=`<apt>`, sprawdź czy
   `<apt>.png` istnieje w autoindexie.

Realny kształt autoindexu (potwierdzony 2026-08-16):
    <a href="0ad.png">0ad.png</a>
    <a href="kcalc.png">kcalc.png</a>
    ...

DEP-11 ID może mieć `.desktop` (np. `org.kde.kcalc.desktop`), Package nie.
"""

import re
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urljoin

from shared.http_client import HttpClient
from shared.logging import log_entry
from shared.pydantic_utils import strict_validate
from shared.types import AppId, HttpUrl, PkgName, Sha256

from domains.corpus.id_norm import strip_desktop_suffix
from domains.corpus.models import CorpusEntry
from domains.corpus.sources.ubuntu_dep11 import (
    Dep11Component,
    UbuntuDep11Source,
)

MINT_BASE = "https://community.linuxmint.com/img/screenshots/"
_HREF_RE = re.compile(r'href="([^"]+\.png)"', re.IGNORECASE)

DEFAULT_WIDTH = 800
DEFAULT_HEIGHT = 600


class MintSource:
    distro = "mint"
    kinds = ("mint-community",)

    def __init__(
        self,
        client: HttpClient | None = None,
        dep11: UbuntuDep11Source | None = None,
    ) -> None:
        self._client = client or HttpClient()
        self._dep11 = dep11 or UbuntuDep11Source(client=self._client)
        self._index_cache: list[str] | None = None
        self._component_to_pkg: dict[str, str] | None = None

    def fetch(self, app: AppId) -> list[dict[str, object]]:
        if self._index_cache is None:
            self._index_cache = self._scrape_index()
        if self._component_to_pkg is None:
            self._component_to_pkg = self._build_dep11_index()
        apt = self._component_to_pkg.get(strip_desktop_suffix(app))
        if not apt:
            log_entry(20, "corpus.mint.no_pkg_mapping", app=app)
            return []
        target = f"{apt}.png"
        if target not in self._index_cache:
            return []
        url = urljoin(MINT_BASE, target)
        now = datetime.now(UTC).isoformat()
        return [
            CorpusEntry(
                app_id=app,
                distro="mint",
                source="mint-community",
                source_url=HttpUrl(url),
                kind="source",
                width=DEFAULT_WIDTH,
                height=DEFAULT_HEIGHT,
                fetched=now,
                sha256=Sha256("0" * 64),
                file="media/unfetched.png",
                pkgname=PkgName(apt),
            ).model_dump(mode="json")
        ]

    def _scrape_index(self) -> list[str]:
        try:
            response = self._client.get(MINT_BASE)
        except Exception as exc:
            log_entry(20, "corpus.mint.fetch_error", error=str(exc))
            return []
        return list(dict.fromkeys(_HREF_RE.findall(response.text)))

    def _build_dep11_index(self) -> dict[str, str]:
        """DEP-11 join: ID → Package, z cache'em response."""
        index: dict[str, str] = {}
        try:
            response = self._client.get(self._dep11._catalog_url())
        except Exception as exc:
            log_entry(20, "corpus.mint.dep11_error", error=str(exc))
            return index
        try:
            import gzip
            import io

            import yaml

            with gzip.open(io.BytesIO(response.content), "rb") as fh:
                docs = list(yaml.safe_load_all(fh))
        except (OSError, yaml.YAMLError) as exc:
            log_entry(20, "corpus.mint.dep11_parse_error", error=str(exc))
            return index
        for doc in docs[1:]:
            if not isinstance(doc, dict) or "ID" not in doc:
                continue
            try:
                comp = strict_validate(Dep11Component, doc)
            except Exception:
                continue
            if comp.Package:
                index[strip_desktop_suffix(comp.ID)] = comp.Package
        log_entry(20, "corpus.mint.dep11_index_built", entries=len(index))
        return index


__all__ = ["DEFAULT_HEIGHT", "DEFAULT_WIDTH", "MintSource"]


def _typecheck_only() -> None:
    Path("/dev/null")

"""Kolektor Ubuntu DEP-11 — YAML wielodokumentowy (archiwum.appstream).

Realny kształt (potwierdzony 2026-08-16 z archive.ubuntu.com/.../noble/main/dep11):

Dokument 0 (header):
    File, Version, Origin, MediaBaseUrl, Time

Dokumenty 1..N (komponenty):
    Type, ID, Package, Name, Summary, Description, ..., Screenshots
    Screenshots[].source-image: {url (relative), width, height}
    Screenshots[].thumbnails[]: {url (relative), width, height}
"""

from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urljoin

import yaml
from pydantic import BaseModel, ConfigDict, Field
from shared.http_client import HttpClient
from shared.logging import log_entry
from shared.pydantic_utils import strict_validate
from shared.types import AppId, HttpUrl, PkgName, Sha256

from domains.corpus.id_norm import strip_desktop_suffix
from domains.corpus.models import CorpusEntry

DEP11_BASE = "http://archive.ubuntu.com/ubuntu/dists"


class Dep11Image(BaseModel):
    model_config = ConfigDict(extra="ignore")

    url: str
    width: int
    height: int


class Dep11Screenshot(BaseModel):
    model_config = ConfigDict(extra="ignore")

    default: bool | None = None
    caption: dict[str, str] | None = None
    source_image: Dep11Image | None = None
    thumbnails: list[Dep11Image] = Field(default_factory=list)


class Dep11Component(BaseModel):
    model_config = ConfigDict(extra="ignore")

    ID: str
    Package: str | None = None
    Name: str | dict[str, str] | None = None
    Summary: str | dict[str, str] | None = None
    Description: str | dict[str, str] | None = None
    Screenshots: list[Dep11Screenshot] = Field(default_factory=list)


class Dep11Header(BaseModel):
    model_config = ConfigDict(extra="ignore")

    MediaBaseUrl: str
    Suite: str | None = None
    Version: str | None = None
    Origin: str | None = None
    Time: str | None = None


class UbuntuDep11Source:
    distro = "ubuntu"
    kinds = ("ubuntu-dep11",)

    def __init__(
        self,
        suite: str = "noble",
        component: str = "main",
        arch: str = "amd64",
        client: HttpClient | None = None,
    ) -> None:
        self._suite = suite
        self._component = component
        self._arch = arch
        self._client = client or HttpClient()

    def fetch(self, app: AppId) -> list[dict[str, object]]:
        url = self._catalog_url()
        try:
            response = self._client.get(url)
        except Exception as exc:
            log_entry(20, "corpus.ubuntu.fetch_error", url=url, error=str(exc))
            return []
        try:
            import gzip
            import io

            with gzip.open(io.BytesIO(response.content), "rb") as fh:
                docs = list(yaml.safe_load_all(fh))
        except (OSError, yaml.YAMLError) as exc:
            log_entry(20, "corpus.ubuntu.parse_error", url=url, error=str(exc))
            return []
        return list(
            iter_dep11_entries(
                docs,
                distro="ubuntu",
                source="ubuntu-dep11",
                apps={strip_desktop_suffix(app)},
            )
        )

    def _catalog_url(self) -> str:
        return f"{DEP11_BASE}/{self._suite}/{self._component}/dep11/Components-{self._arch}.yml.gz"


def iter_dep11_entries(
    docs: list[Any],
    *,
    distro: str,
    source: str,
    apps: set[str] | None = None,
    notes: str | None = None,
) -> Iterator[dict[str, object]]:
    """Wpisy korpusu dla screenshotów z dokumentów DEP-11 (nagłówek + komponenty).

    Używane zarówno dla katalogu z archiwum Ubuntu (`fetch`), jak i dla plików
    `Components-amd64.yml.gz` zebranych z wnętrza gościa. `apps` = znormalizowane
    id (bez `.desktop`); ``None`` = wszystkie komponenty.
    """
    if not docs:
        return
    try:
        header = strict_validate(Dep11Header, docs[0])
    except Exception as exc:
        log_entry(20, "corpus.ubuntu.bad_header", error=str(exc))
        return
    media_base = header.MediaBaseUrl
    if not media_base.endswith("/"):
        media_base += "/"
    now = datetime.now(UTC)
    for doc in docs[1:]:
        if not isinstance(doc, dict) or "ID" not in doc:
            continue
        try:
            comp = strict_validate(Dep11Component, doc)
        except Exception:
            continue
        cid = strip_desktop_suffix(comp.ID)
        if apps is not None and cid not in apps:
            continue
        pkg = PkgName(comp.Package) if comp.Package else None
        for shot in comp.Screenshots:
            images: list[tuple[str, int, int, str]] = []
            if shot.source_image and shot.source_image.url:
                images.append(
                    (
                        shot.source_image.url,
                        shot.source_image.width,
                        shot.source_image.height,
                        "source",
                    )
                )
            images.extend(
                (thumb.url, thumb.width, thumb.height, "thumbnail")
                for thumb in shot.thumbnails
                if thumb.url
            )
            for url_text, width, height, kind in images:
                full_url = (
                    urljoin(media_base, url_text) if not url_text.startswith("http") else url_text
                )
                try:
                    entry = CorpusEntry(
                        app_id=AppId(cid),
                        distro=distro,
                        source=source,
                        source_url=HttpUrl(full_url),
                        kind=kind,
                        width=width,
                        height=height,
                        fetched=now,
                        sha256=Sha256("0" * 64),
                        file="media/unfetched.png",
                        pkgname=pkg,
                        notes=notes,
                    )
                except Exception as exc:
                    log_entry(20, "corpus.dep11.entry_invalid", app=cid, error=str(exc))
                    continue
                yield entry.model_dump(mode="json")


__all__ = [
    "Dep11Component",
    "Dep11Header",
    "Dep11Image",
    "Dep11Screenshot",
    "UbuntuDep11Source",
    "iter_dep11_entries",
]

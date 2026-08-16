"""Kolektor Ubuntu DEP-11 — YAML wielodokumentowy (archiwum.appstream).

Realny kształt (potwierdzony 2026-08-16 z archive.ubuntu.com/.../noble/main/dep11):

Dokument 0 (header):
    File, Version, Origin, MediaBaseUrl, Time

Dokumenty 1..N (komponenty):
    Type, ID, Package, Name, Summary, Description, ..., Screenshots
    Screenshots[].source-image: {url (relative), width, height}
    Screenshots[].thumbnails[]: {url (relative), width, height}
"""

from datetime import UTC, datetime
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
        if not docs:
            return []
        try:
            header = strict_validate(Dep11Header, docs[0])
        except Exception as exc:
            log_entry(20, "corpus.ubuntu.bad_header", error=str(exc))
            return []
        media_base = header.MediaBaseUrl
        if not media_base.endswith("/"):
            media_base += "/"
        target = strip_desktop_suffix(app)
        now = datetime.now(UTC).isoformat()
        entries: list[dict[str, object]] = []
        for doc in docs[1:]:
            if not isinstance(doc, dict) or "ID" not in doc:
                continue
            try:
                comp = strict_validate(Dep11Component, doc)
            except Exception:
                continue
            if strip_desktop_suffix(comp.ID) != target:
                continue
            for shot in comp.Screenshots:
                if shot.source_image and shot.source_image.url:
                    url_text = shot.source_image.url
                    full_url = (
                        urljoin(media_base, url_text)
                        if not url_text.startswith("http")
                        else url_text
                    )
                    entries.append(
                        CorpusEntry(
                            app_id=AppId(target),
                            distro="ubuntu",
                            source="ubuntu-dep11",
                            source_url=HttpUrl(full_url),
                            kind="source",
                            width=shot.source_image.width,
                            height=shot.source_image.height,
                            fetched=now,
                            sha256=Sha256("0" * 64),
                            file="media/unfetched.png",
                            pkgname=PkgName(comp.Package) if comp.Package else None,
                        ).model_dump(mode="json")
                    )
                for thumb in shot.thumbnails:
                    if not thumb.url:
                        continue
                    url_text = thumb.url
                    full_url = (
                        urljoin(media_base, url_text)
                        if not url_text.startswith("http")
                        else url_text
                    )
                    entries.append(
                        CorpusEntry(
                            app_id=AppId(target),
                            distro="ubuntu",
                            source="ubuntu-dep11",
                            source_url=HttpUrl(full_url),
                            kind="thumbnail",
                            width=thumb.width,
                            height=thumb.height,
                            fetched=now,
                            sha256=Sha256("0" * 64),
                            file="media/unfetched.png",
                            pkgname=PkgName(comp.Package) if comp.Package else None,
                        ).model_dump(mode="json")
                    )
        return entries

    def _catalog_url(self) -> str:
        return f"{DEP11_BASE}/{self._suite}/{self._component}/dep11/Components-{self._arch}.yml.gz"


__all__ = [
    "Dep11Component",
    "Dep11Header",
    "Dep11Image",
    "Dep11Screenshot",
    "UbuntuDep11Source",
]

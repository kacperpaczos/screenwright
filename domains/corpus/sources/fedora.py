"""Kolektor Fedora — pobiera appstream-data RPM i parsuje fedora.xml.gz.

Realny kształt (potwierdzony 2026-08-16 z appstream-data-44-1.fc44.noarch.rpm):

    <components origin="fedora" version="0.8">
      <component type="desktop">
        <id>org.kde.kcalc.desktop</id>
        <pkgname>kcalc</pkgname>
        <name>KCalc</name>
        <screenshots>
          <screenshot>
            <image type="source" width="1200" height="675">https://cdn.kde.org/...</image>
            <image type="thumbnail" width="752" height="423">https://cdn.kde.org/...</image>
          </screenshot>
        </screenshots>
      </component>
    </components>

BEZ namespacu — inaczej niż mylnie zakładały wcześniejsze wersje.
"""

from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urljoin
from xml.etree.ElementTree import Element, fromstring

from shared.http_client import HttpClient
from shared.logging import log_entry
from shared.pydantic_utils import construct_validated
from shared.types import AppId, HttpUrl

from domains.corpus.id_norm import strip_desktop_suffix
from domains.corpus.models import CorpusEntry


class FedoraSource:
    distro = "fedora"
    kinds = ("fedora-appstream",)

    def __init__(self, client: HttpClient | None = None) -> None:
        self._client = client or HttpClient()

    def fetch(self, app: AppId) -> list[dict[str, object]]:
        for url in self._resolve_appstream_urls():
            xml_root = self._fetch_catalog(url)
            if xml_root is None:
                continue
            entries = self._extract_for_app(xml_root, app)
            if entries:
                return entries
        return []

    def _resolve_appstream_urls(self) -> list[str]:
        return [
            "https://dl.fedoraproject.org/pub/alt/screenshots/f44/fedora.xml.gz",
        ]

    def _fetch_catalog(self, url: str) -> Element | None:
        try:
            response = self._client.get(url)
        except Exception as exc:
            log_entry(20, "corpus.fedora.fetch_error", url=url, error=str(exc))
            return None
        try:
            import gzip
            import io

            with gzip.open(io.BytesIO(response.content), "rb") as fh:
                return fromstring(fh.read())
        except (OSError, ValueError) as exc:
            log_entry(20, "corpus.fedora.parse_error", url=url, error=str(exc))
            return None

    def _extract_for_app(self, root: Element, app: AppId) -> list[dict[str, object]]:
        media_base = root.attrib.get("media_baseurl", "")
        if media_base and not media_base.endswith("/"):
            media_base += "/"
        target = strip_desktop_suffix(app)
        now = datetime.now(UTC).isoformat()
        results: list[dict[str, object]] = []
        for component in root.findall("component"):
            cid_node = component.find("id")
            if cid_node is None or cid_node.text is None:
                continue
            if strip_desktop_suffix(cid_node.text) != target:
                continue
            cid = AppId(target)
            pkgname = component.findtext("pkgname")
            for screenshot in component.findall(".//screenshot"):
                for image in screenshot.findall("image"):
                    image_type = image.attrib.get("type", "source")
                    width = self._parse_int(image.attrib.get("width"), DEFAULT_WIDTH)
                    height = self._parse_int(image.attrib.get("height"), DEFAULT_HEIGHT)
                    url_text = (image.text or "").strip()
                    if not url_text:
                        continue
                    full_url = (
                        urljoin(media_base, url_text)
                        if media_base and not url_text.startswith("http")
                        else url_text
                    )
                    entry = construct_validated(
                        CorpusEntry,
                        {
                            "app_id": cid,
                            "distro": "fedora",
                            "source": "fedora-appstream",
                            "source_url": HttpUrl(full_url),
                            "kind": "source" if image_type == "source" else "thumbnail",
                            "width": width,
                            "height": height,
                            "fetched": now,
                            "sha256": "0" * 64,
                            "file": "media/unfetched.png",
                            "pkgname": pkgname,
                            "notes": None,
                        },
                        sample_rate=100,
                    ).model_dump(mode="json")
                    results.append(entry)
        return results

    @staticmethod
    def _parse_int(value: object, default: int) -> int:
        if value is None:
            return default
        if isinstance(value, str) and value:
            try:
                return int(value)
            except ValueError:
                return default
        return default


DEFAULT_WIDTH = 1280
DEFAULT_HEIGHT = 720


__all__ = ["DEFAULT_HEIGHT", "DEFAULT_WIDTH", "FedoraSource"]


def _unused(_: Any) -> None:
    Path("/dev/null")

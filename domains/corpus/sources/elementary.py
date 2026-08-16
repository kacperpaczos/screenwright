"""Kolektor elementary OS — flatpak repo z appstream.xml.gz.

Realny kształt (potwierdzony 2026-08-16 z flatpak.elementaryos.org/repo/appstream/x86_64/appstream.xml.gz):

    <components version="0.8" origin="flatpak">
      <component>
        <id>io.elementary.calculator</id>
        <name>Calculator</name>
        <screenshots>
          <screenshot type="default">
            <caption>...</caption>
            <image type="source" width="658" height="742">https://raw.githubusercontent.com/...</image>
          </screenshot>
        </screenshots>
      </component>
    </components>

BEZ namespacu.
"""

from datetime import UTC, datetime
from urllib.parse import urljoin
from xml.etree.ElementTree import fromstring

from shared.http_client import HttpClient
from shared.logging import log_entry
from shared.types import AppId, HttpUrl, Sha256

from domains.corpus.id_norm import strip_desktop_suffix
from domains.corpus.models import CorpusEntry

ELEMENTARY_REPO = "https://flatpak.elementaryos.org/repo/appstream/x86_64/appstream.xml.gz"

DEFAULT_WIDTH = 1280
DEFAULT_HEIGHT = 720


class ElementarySource:
    distro = "elementary"
    kinds = ("elementary-repo",)

    def __init__(self, client: HttpClient | None = None) -> None:
        self._client = client or HttpClient()

    def fetch(self, app: AppId) -> list[dict[str, object]]:
        try:
            response = self._client.get(ELEMENTARY_REPO)
        except Exception as exc:
            log_entry(20, "corpus.elementary.fetch_error", error=str(exc))
            return []
        try:
            import gzip
            import io

            with gzip.open(io.BytesIO(response.content), "rb") as fh:
                root = fromstring(fh.read())
        except (OSError, ValueError) as exc:
            log_entry(20, "corpus.elementary.parse_error", error=str(exc))
            return []
        media_base = root.attrib.get("media_baseurl", ELEMENTARY_REPO)
        if not media_base.endswith("/"):
            media_base += "/"
        target = strip_desktop_suffix(app)
        now = datetime.now(UTC).isoformat()
        entries: list[dict[str, object]] = []
        for component in root.findall("component"):
            cid = component.findtext("id") or ""
            if strip_desktop_suffix(cid) != target:
                continue
            for shot in component.findall(".//screenshot"):
                for img in shot.findall("image"):
                    raw_url = (img.text or "").strip()
                    if not raw_url:
                        continue
                    width = self._parse_int(img.attrib.get("width"), DEFAULT_WIDTH)
                    height = self._parse_int(img.attrib.get("height"), DEFAULT_HEIGHT)
                    full_url = (
                        urljoin(media_base, raw_url) if not raw_url.startswith("http") else raw_url
                    )
                    entries.append(
                        CorpusEntry(
                            app_id=AppId(target),
                            distro="elementary",
                            source="elementary-repo",
                            source_url=HttpUrl(full_url),
                            kind="source" if img.attrib.get("type") == "source" else "thumbnail",
                            width=width,
                            height=height,
                            fetched=now,
                            sha256=Sha256("0" * 64),
                            file="media/unfetched.png",
                        ).model_dump(mode="json")
                    )
        return entries

    @staticmethod
    def _parse_int(value: object, default: int) -> int:
        """Bezpieczny parse int: None/invalid → default."""
        if value is None:
            return default
        if isinstance(value, str) and value:
            try:
                return int(value)
            except ValueError:
                return default
        return default


__all__ = ["DEFAULT_HEIGHT", "DEFAULT_WIDTH", "ElementarySource"]

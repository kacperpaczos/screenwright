"""Kolektor Debian — screenshots.debian.net/community uploads.

Realny kształt (potwierdzony 2026-08-16 z screenshots.debian.net/json/package/kcalc):

{
  "package": "kcalc",
  "screenshots": [
    {
      "thumb_image_url": "https://screenshots.debian.net/thumbnail/kcalc/25411",
      "small_image_url": "https://screenshots.debian.net/small/kcalc/25411",
      "screenshot_image_url": "https://screenshots.debian.net/screenshot/kcalc/25411",
      "version": "23.08.2"
    }
  ]
}

API NIE zwraca wymiarów obrazu — używamy stałych wymiarów zgodnych z konwencją
Fedora (domyślne dla screenshotów w sklepach).
"""

from datetime import UTC, datetime

from pydantic import BaseModel, ConfigDict, Field
from shared.http_client import HttpClient
from shared.logging import log_entry
from shared.pydantic_utils import strict_validate
from shared.types import AppId, HttpUrl, PkgName, Sha256

from domains.corpus.models import CorpusEntry

DEBIAN_SCREENSHOTS_API = "https://screenshots.debian.net/json/package"

DEFAULT_THUMB_WIDTH = 752
DEFAULT_THUMB_HEIGHT = 423
DEFAULT_SOURCE_WIDTH = 1280
DEFAULT_SOURCE_HEIGHT = 720


class DebianScreenshotEntry(BaseModel):
    model_config = ConfigDict(extra="ignore")

    thumb_image_url: str | None = None
    small_image_url: str | None = None
    screenshot_image_url: str | None = None
    version: str | None = None


class DebianScreenshotResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    package: str | None = None
    screenshots: list[DebianScreenshotEntry] = Field(default_factory=list)


class DebianSource:
    distro = "debian"
    kinds = ("debian-screenshots-net",)

    def __init__(self, client: HttpClient | None = None) -> None:
        self._client = client or HttpClient()

    def fetch(self, app: AppId) -> list[dict[str, object]]:
        url = f"{DEBIAN_SCREENSHOTS_API}/{app}"
        try:
            response = self._client.get(url)
        except Exception as exc:
            log_entry(20, "corpus.debian.fetch_error", app=app, error=str(exc))
            return []
        try:
            payload = strict_validate(DebianScreenshotResponse, response.json())
        except Exception as exc:
            log_entry(20, "corpus.debian.parse_error", app=app, error=str(exc))
            return []
        now = datetime.now(UTC).isoformat()
        entries: list[dict[str, object]] = []
        for shot in payload.screenshots:
            if shot.screenshot_image_url:
                entries.append(
                    CorpusEntry(
                        app_id=app,
                        distro="debian",
                        source="debian-screenshots-net",
                        source_url=HttpUrl(shot.screenshot_image_url),
                        kind="source",
                        width=DEFAULT_SOURCE_WIDTH,
                        height=DEFAULT_SOURCE_HEIGHT,
                        fetched=now,
                        sha256=Sha256("0" * 64),
                        file="media/unfetched.png",
                        pkgname=PkgName(payload.package) if payload.package else None,
                        notes=f"version={shot.version}" if shot.version else None,
                    ).model_dump(mode="json")
                )
            if shot.thumb_image_url:
                entries.append(
                    CorpusEntry(
                        app_id=app,
                        distro="debian",
                        source="debian-screenshots-net",
                        source_url=HttpUrl(shot.thumb_image_url),
                        kind="thumbnail",
                        width=DEFAULT_THUMB_WIDTH,
                        height=DEFAULT_THUMB_HEIGHT,
                        fetched=now,
                        sha256=Sha256("0" * 64),
                        file="media/unfetched.png",
                        pkgname=PkgName(payload.package) if payload.package else None,
                        notes=f"version={shot.version}" if shot.version else None,
                    ).model_dump(mode="json")
                )
        return entries


__all__ = [
    "DEFAULT_SOURCE_HEIGHT",
    "DEFAULT_SOURCE_WIDTH",
    "DEFAULT_THUMB_HEIGHT",
    "DEFAULT_THUMB_WIDTH",
    "DebianScreenshotEntry",
    "DebianScreenshotResponse",
    "DebianSource",
]

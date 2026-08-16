"""Kolektor Flathub — API v2 (per app).

Realny kształt odpowiedzi (potwierdzony 2026-08-16):
{
  "id": "org.kde.kcalc",
  "name": "KCalc",
  "screenshots": [
    {
      "default": true,
      "caption": "...",
      "sizes": [
        {"width": "487", "height": "575", "scale": "1x", "src": "https://..."},
        {"width": "224", "height": "264", "scale": "1x", "src": "https://..."}
      ]
    }
  ]
}
"""

from datetime import UTC, datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator
from shared.http_client import HttpClient
from shared.logging import log_entry
from shared.pydantic_utils import strict_validate
from shared.types import AppId, HttpUrl, Sha256

from domains.corpus.id_norm import strip_desktop_suffix
from domains.corpus.models import CorpusEntry

FLATHUB_API = "https://flathub.org/api/v2/appstream"


class FlathubScreenshotSize(BaseModel):
    model_config = ConfigDict(extra="ignore")

    width: str
    height: str
    scale: str | None = None
    src: str

    @property
    def width_int(self) -> int:
        return int(self.width)

    @property
    def height_int(self) -> int:
        return int(self.height)


class FlathubScreenshot(BaseModel):
    model_config = ConfigDict(extra="ignore")

    default: bool | None = None
    caption: str | None = None
    sizes: list[FlathubScreenshotSize] = Field(default_factory=list)


class FlathubApiResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str
    name: str | None = None
    screenshots: list[FlathubScreenshot] = Field(default_factory=list)

    @field_validator("id")
    @classmethod
    def _id_nonempty(cls, v: str) -> str:
        if not v:
            raise ValueError("id is empty")
        return v

    def to_canonical(self) -> str:
        return strip_desktop_suffix(self.id)


class FlathubSource:
    """Pobiera metadane z Flathub API v2."""

    distro = "flathub"
    kinds = ("flathub-api",)

    def __init__(self, client: HttpClient | None = None) -> None:
        self._client = client or HttpClient()

    def fetch(self, app: AppId) -> list[dict[str, object]]:
        url = f"{FLATHUB_API}/{app}"
        try:
            response = self._client.get(url)
        except Exception as exc:
            log_entry(20, "corpus.flathub.fetch_error", app=app, error=str(exc))
            return []
        try:
            payload = strict_validate(FlathubApiResponse, response.json())
        except Exception as exc:
            log_entry(20, "corpus.flathub.parse_error", app=app, error=str(exc))
            return []
        return self._to_entries(payload)

    def _to_entries(self, payload: FlathubApiResponse) -> list[dict[str, object]]:
        now = datetime.now(UTC).isoformat()
        app_id = AppId(payload.to_canonical())
        entries: list[dict[str, object]] = []
        for shot in payload.screenshots:
            for size in shot.sizes:
                # URL pattern: "*_orig.png" → source; "*_WxH@Nx.png" → thumbnail.
                # Pole `scale` mówi tylko o DPI ("1x", "2x"), nie rozróżnia.
                kind = "source" if "_orig" in size.src else "thumbnail"
                entries.append(
                    CorpusEntry(
                        app_id=app_id,
                        distro="flathub",
                        source="flathub-api",
                        source_url=HttpUrl(size.src),
                        kind=kind,
                        width=size.width_int,
                        height=size.height_int,
                        fetched=now,
                        sha256=Sha256("0" * 64),
                        file="media/unfetched.png",
                        notes=shot.caption,
                    ).model_dump(mode="json")
                )
        return entries


__all__ = [
    "FlathubApiResponse",
    "FlathubScreenshot",
    "FlathubScreenshotSize",
    "FlathubSource",
]

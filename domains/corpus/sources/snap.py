"""Kolektor Snap Store — API v2 z nagłówkiem Snap-Device-Series.

Realny kształt (potwierdzony 2026-08-16 z api.snapcraft.io/v2/snaps/info/<snap>?fields=media):

{
  "snap": {
    "media": [
      {"type": "icon",        "url": "...", "width": 256, "height": 256},
      {"type": "screenshot",  "url": "...", "width": 487, "height": 575},
      ...
    ]
  }
}
"""

from datetime import UTC, datetime

from pydantic import BaseModel, ConfigDict, Field
from shared.http_client import HttpClient
from shared.logging import log_entry
from shared.pydantic_utils import strict_validate
from shared.types import AppId, HttpUrl, Sha256

from domains.corpus.models import CorpusEntry

SNAP_API = "https://api.snapcraft.io/v2"


class SnapMediaItem(BaseModel):
    model_config = ConfigDict(extra="ignore")

    type: str
    url: str
    width: int | None = None
    height: int | None = None


class SnapMediaInner(BaseModel):
    model_config = ConfigDict(extra="ignore")

    media: list[SnapMediaItem] = Field(default_factory=list)


class SnapInfoResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    snap: SnapMediaInner = Field(default_factory=SnapMediaInner)


class SnapSource:
    distro = "snap"
    kinds = ("snap-store",)

    def __init__(self, client: HttpClient | None = None) -> None:
        self._client = client or HttpClient()

    def fetch(self, app: AppId) -> list[dict[str, object]]:
        url = f"{SNAP_API}/snaps/info/{app}?fields=media"
        try:
            response = self._client.get(url, snap=True)
        except Exception as exc:
            log_entry(20, "corpus.snap.fetch_error", app=app, error=str(exc))
            return []
        try:
            payload = strict_validate(SnapInfoResponse, response.json())
        except Exception as exc:
            log_entry(20, "corpus.snap.parse_error", app=app, error=str(exc))
            return []
        now = datetime.now(UTC).isoformat()
        entries: list[dict[str, object]] = []
        for item in payload.snap.media:
            if item.type != "screenshot" or item.width is None or item.height is None:
                continue
            entries.append(
                CorpusEntry(
                    app_id=app,
                    distro="snap",
                    source="snap-store",
                    source_url=HttpUrl(item.url),
                    kind="source",
                    width=item.width,
                    height=item.height,
                    fetched=now,
                    sha256=Sha256("0" * 64),
                    file="media/unfetched.png",
                ).model_dump(mode="json")
            )
        return entries


__all__ = ["SnapInfoResponse", "SnapMediaInner", "SnapMediaItem", "SnapSource"]

"""Modele pydantic domeny corpus."""

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from shared.types import AppId, HttpUrl, PkgName, RelativePath, Sha256

Distro = Literal[
    "fedora",
    "ubuntu",
    "mint",
    "elementary",
    "flathub",
    "snap",
    "debian",
]

SourceKind = Literal[
    "fedora-appstream",
    "fedora-thumbnails",
    "flathub-api",
    "flathub-raw",
    "ubuntu-dep11",
    "snap-store",
    "debian-dep11",
    "debian-screenshots-net",
    "mint-community",
    "elementary-repo",
    "guest-appstream",
    "guest-dep11",
    "guest-flatpak",
    "guest-snapd",
]


class CorpusEntry(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    app_id: AppId
    distro: Distro
    source: SourceKind
    source_url: HttpUrl
    kind: Literal["source", "thumbnail"]
    width: int = Field(ge=1, le=10000)
    height: int = Field(ge=1, le=10000)
    fetched: datetime
    sha256: Sha256
    file: RelativePath
    pkgname: PkgName | None = None
    notes: str | None = None

    @field_validator("fetched")
    @classmethod
    def _validate_fetched(cls, v: datetime) -> datetime:
        if v.tzinfo is None:
            v = v.replace(tzinfo=UTC)
        now = datetime.now(UTC)
        if v > now + timedelta(minutes=5):
            raise ValueError("fetched cannot be in the future")
        if v < now - timedelta(days=365 * 5):
            raise ValueError("fetched too old (>5y)")
        return v

    @model_validator(mode="after")
    def _check_consistency(self) -> "CorpusEntry":
        if self.kind == "source" and (self.width < 100 or self.height < 100):
            raise ValueError("source images must be >=100x100")
        if self.kind == "thumbnail" and (self.width >= 1000 or self.height >= 1000):
            raise ValueError("thumbnails should be <1000px")
        return self


class CorpusIndex(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1] = 1
    entries: list[CorpusEntry] = Field(default_factory=list)

    def has(
        self,
        source_url: HttpUrl,
        sha256: Sha256,
        since: datetime | None = None,
    ) -> bool:
        for entry in self.entries:
            if entry.source_url != source_url:
                continue
            if entry.sha256 != sha256:
                continue
            if since is not None and entry.fetched < since:
                continue
            return True
        return False

    def append(self, entry: CorpusEntry) -> None:
        object.__setattr__(self, "entries", [*self.entries, entry])

    @classmethod
    def from_raw(cls, raw: list[dict[str, Any]]) -> "CorpusIndex":
        return cls(entries=[CorpusEntry.model_validate(e) for e in raw])


__all__ = [
    "CorpusEntry",
    "CorpusIndex",
    "Distro",
    "SourceKind",
]


def _typecheck_only(_: Path) -> None:
    pass

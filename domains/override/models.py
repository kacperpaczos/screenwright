"""Modele pydantic domeny override."""

from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field
from shared.types import ComponentId, HttpUrl


class OverrideSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    component_id: ComponentId
    base_url: HttpUrl
    prefix: str = Field(pattern=r"^[a-z0-9_-]+$")
    out: Path
    origin: str = "screenwright"
    priority: int = Field(ge=1)
    caption: str = "screenwright - generated automatically under Xvfb"
    source_size: tuple[int, int] = (640, 480)
    catalog_paths: list[Path] = Field(
        default_factory=lambda: [Path("/usr/share/swcatalog/xml/fedora.xml.gz")]
    )


class OverrideResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    out_path: Path
    origin: str
    priority: int
    replaced_screenshots: int = Field(ge=0)


__all__ = ["OverrideResult", "OverrideSpec"]

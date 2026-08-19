"""Modele pydantic domeny matrix."""

import uuid
from enum import StrEnum
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator
from shared.types import AppId, HttpUrl


class DistroName(StrEnum):
    FEDORA_KDE = "fedora-kde"
    FEDORA_WS = "fedora-ws"
    UBUNTU = "ubuntu-24.04"
    MINT = "mint-22"
    ELEMENTARY = "elementary-8"


class DistroSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: DistroName
    golden_image: Path
    build_artifact: Path | None = None
    installer_iso: HttpUrl | None = None
    domain_overrides: dict[str, Any] = Field(default_factory=dict)
    store_proxy: Literal["snap-store"] | None = None
    seed_iso: Path | None = None
    """NoCloud seed ISO podpinane jako cdrom przy tworzeniu domeny.

    cloud-init w gościu szuka wolumenu z etykietą ``cidata``; bez podpięcia
    seed ISO do domeny (a nie tylko na czas ``virt-customize``) user-data
    nigdy nie zostanie zaaplikowane. Patrz ``vm/build/seed-ubuntu.sh``.
    """

    @field_validator("golden_image", "build_artifact", "seed_iso", mode="after")
    @classmethod
    def _expand_user(cls, v: Path | None) -> Path | None:
        """`~` w spec JSON-ie ma działać — obrazy leżą w HOME (tryb session)."""
        return v.expanduser() if v is not None else None


class DomainConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(pattern=r"^[a-z0-9-]+$")
    memory_mib: int = Field(ge=512, le=65536)
    vcpus: int = Field(ge=1, le=64)
    disk_gib: int = Field(ge=5, le=500)
    graphics: Literal["spice", "vnc"] = "vnc"
    listen: str = "127.0.0.1"
    enable_3d: Literal[False] = False
    ssh_port: int = Field(ge=1024, le=65535, default=2222)
    """Port na 127.0.0.1 przekierowany do portu 22 gościa (passt).

    W ``qemu:///session`` gość siedzi za usermode NAT-em i nie ma adresu
    osiągalnego z hosta, więc bez tego przekierowania nie ma jak wejść po
    SSH. Runner nadaje każdej domenie wolny port, żeby dwie równoległe
    maszyny się nie pobiły.
    """


class MatrixRunSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    apps: list[AppId] = Field(min_length=1)
    distros: list[DistroSpec] = Field(min_length=1)
    batch: int = Field(ge=1, le=8, default=2)
    dry_run: bool = True
    output_dir: Path = Path("vm/reports")
    templates_dir: Path | None = None
    verify_threshold: float = Field(default=0.85, ge=0.0, le=1.0)

    @field_validator("distros")
    @classmethod
    def _unique_distros(cls, v: list[DistroSpec]) -> list[DistroSpec]:
        seen: set[str] = set()
        for d in v:
            if d.name in seen:
                raise ValueError(f"duplicate distro: {d.name}")
            seen.add(d.name)
        return v


_MATRIX_STEP_VERBS = Literal[
    "create-overlay",
    "define",
    "create",
    "start",
    "screenshot",
    "verify",
    "destroy",
    "qemu-agent-exec",
]


class MatrixStep(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    sequence: int
    run_id: str
    distro: DistroName
    app: AppId
    verb: _MATRIX_STEP_VERBS
    args: dict[str, Any] = Field(default_factory=dict)
    expected_exit: int = 0

    @classmethod
    def new(
        cls,
        *,
        sequence: int,
        distro: DistroName,
        app: AppId,
        verb: _MATRIX_STEP_VERBS,
        args: dict[str, Any] | None = None,
        run_id: str | None = None,
    ) -> "MatrixStep":
        return cls(
            sequence=sequence,
            run_id=run_id or uuid.uuid4().hex[:8],
            distro=distro,
            app=app,
            verb=verb,
            args=args or {},
        )


__all__ = [
    "_MATRIX_STEP_VERBS",
    "DistroName",
    "DistroSpec",
    "DomainConfig",
    "MatrixRunSpec",
    "MatrixStep",
]

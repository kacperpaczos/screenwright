"""Warm cache — zamrożony RAM + dysk klona per dystrybucja (``virsh save`` / ``restore --xml``).

Szablon leży w ``<root>/<distro>/``:

- ``base.qcow2`` — overlay na golden, na którym gość zbootował do gotowej sesji;
  po ``save`` zamrożony (nikt już do niego nie pisze),
- ``state.save`` — RAM domeny (``virsh save``; ``save_image_format`` z
  ``~/.config/libvirt/qemu.conf`` — zstd daje ~1 GB przy 4 GiB gościa),
- ``domain.xml`` — dokładny XML użyty przy ``virsh create`` (te same name/uuid/MAC),
- ``manifest.json`` — co i na czym zapisano (golden, sprzęt, hypervisor, port).

Każdy przebieg tworzy **świeży** ``disk.qcow2`` z backing=``base.qcow2`` pod tą
samą ścieżką, pod którą dysk był przy ``save``, i robi ``virsh restore --xml
domain.xml state.save``: libvirt sprawdza zgodność ABI z zapisanym stanem, a
łańcuch backing bierze z nagłówka qcow2 (sprawdzone na żywo 2026-08-22: restore
5.7 s, agent i passt od razu, domena dalej transient). Stała nazwa domeny
``sw-<distro>-warm`` bierze się stąd, że restore wymaga tej samej nazwy co save.

Szablon jest nieważny, gdy zmienił się golden (rozmiar/mtime), sprzęt klona
(``domain_overrides``), hypervisor (``cache_key``) albo port SSH jest zajęty.
Nieczytelny stan nie wywala przebiegu: runner loguje, kasuje szablon i bootuje
na zimno (budując go od nowa) — decyzja z 2026-08-21.
"""

from __future__ import annotations

import fcntl
import socket
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, ConfigDict, ValidationError
from shared.logging import log_entry

from domains.matrix.models import RUNNER_OWNED_DOMAIN_FIELDS

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

    from domains.matrix.models import DistroName, DistroSpec, DomainConfig

BASE_NAME = "base.qcow2"
DISK_NAME = "disk.qcow2"
STATE_NAME = "state.save"
XML_NAME = "domain.xml"
MANIFEST_NAME = "manifest.json"
LOCK_NAME = ".lock"


class WarmManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    ssh_port: int
    golden: str
    golden_size: int
    golden_mtime_ns: int
    hardware: dict[str, Any]
    cache_key: str = ""
    created_at: datetime


@dataclass(frozen=True)
class WarmTemplate:
    directory: Path
    manifest: WarmManifest

    @property
    def base(self) -> Path:
        return self.directory / BASE_NAME

    @property
    def disk(self) -> Path:
        return self.directory / DISK_NAME

    @property
    def state(self) -> Path:
        return self.directory / STATE_NAME

    @property
    def xml(self) -> Path:
        return self.directory / XML_NAME


def hardware_of(domain: DomainConfig) -> dict[str, Any]:
    """Sprzęt klona bez pól nadawanych przez runner — klucz zgodności szablonu."""
    return domain.model_dump(mode="json", exclude=set(RUNNER_OWNED_DOMAIN_FIELDS))


def template_name(distro: DistroName) -> str:
    return f"sw-{distro.value.replace('.', '-')}-warm"


def port_is_free(port: int, host: str = "127.0.0.1") -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        try:
            sock.bind((host, port))
        except OSError:
            return False
    return True


class WarmCache:
    def __init__(self, root: Path, *, cache_key: str = "") -> None:
        self.root = root
        self.cache_key = cache_key

    def directory(self, distro: DistroName) -> Path:
        return self.root / distro.value

    def lookup(self, distro: DistroSpec, hardware: dict[str, Any]) -> WarmTemplate | None:
        """Zwraca szablon tylko wtedy, gdy wszystko się zgadza; powód odmowy idzie do logu."""
        directory = self.directory(distro.name)
        manifest_path = directory / MANIFEST_NAME
        if not manifest_path.exists():
            return None
        try:
            manifest = WarmManifest.model_validate_json(manifest_path.read_text(encoding="utf-8"))
        except ValidationError as exc:
            log_entry(30, "matrix.warm.manifest_invalid", distro=distro.name.value, error=str(exc))
            return None
        template = WarmTemplate(directory=directory, manifest=manifest)
        reasons = [
            f"missing {f.name}"
            for f in (template.base, template.state, template.xml)
            if not f.exists()
        ]
        golden = distro.golden_image
        if not golden.exists():
            reasons.append("golden missing")
        else:
            stat = golden.stat()
            if (
                manifest.golden != str(golden)
                or manifest.golden_size != stat.st_size
                or manifest.golden_mtime_ns != stat.st_mtime_ns
            ):
                reasons.append("golden changed")
        if manifest.hardware != hardware:
            reasons.append("hardware changed")
        if manifest.cache_key != self.cache_key:
            reasons.append("hypervisor changed")
        if not port_is_free(manifest.ssh_port):
            reasons.append(f"ssh port {manifest.ssh_port} busy")
        if reasons:
            log_entry(20, "matrix.warm.miss", distro=distro.name.value, reasons=reasons)
            return None
        return template

    def prepare(self, distro: DistroName, xml: str) -> Path:
        """Czyści katalog szablonu i zapisuje XML; zwraca ścieżkę dysku, na którym ma bootować klon."""
        self.invalidate(distro)
        directory = self.directory(distro)
        directory.mkdir(parents=True, exist_ok=True)
        (directory / XML_NAME).write_text(xml, encoding="utf-8")
        return directory / DISK_NAME

    def commit(
        self,
        distro: DistroSpec,
        *,
        name: str,
        ssh_port: int,
        hardware: dict[str, Any],
    ) -> WarmTemplate:
        """Po udanym ``save``: zamraża dysk (``disk`` → ``base``) i zapisuje manifest."""
        directory = self.directory(distro.name)
        (directory / DISK_NAME).rename(directory / BASE_NAME)
        stat = distro.golden_image.stat()
        manifest = WarmManifest(
            name=name,
            ssh_port=ssh_port,
            golden=str(distro.golden_image),
            golden_size=stat.st_size,
            golden_mtime_ns=stat.st_mtime_ns,
            hardware=hardware,
            cache_key=self.cache_key,
            created_at=datetime.now(UTC),
        )
        (directory / MANIFEST_NAME).write_text(manifest.model_dump_json(indent=2), encoding="utf-8")
        log_entry(
            20, "matrix.warm.built", distro=distro.name.value, name=name, directory=str(directory)
        )
        return WarmTemplate(directory=directory, manifest=manifest)

    def invalidate(self, distro: DistroName) -> None:
        directory = self.directory(distro)
        for file_name in (BASE_NAME, DISK_NAME, STATE_NAME, XML_NAME, MANIFEST_NAME):
            (directory / file_name).unlink(missing_ok=True)

    @contextmanager
    def lock(self, distro: DistroName) -> Iterator[bool]:
        """Nieblokująca blokada katalogu szablonu na czas przebiegu.

        Dwa przebiegi na tej samej dystrybucji pobiłyby się o stałą nazwę domeny
        i o ``disk.qcow2``; przegrany dostaje ``False`` i ma bootować po staremu.
        """
        directory = self.directory(distro)
        directory.mkdir(parents=True, exist_ok=True)
        handle = (directory / LOCK_NAME).open("a+")
        try:
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError:
                yield False
                return
            try:
                yield True
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        finally:
            handle.close()


__all__ = [
    "BASE_NAME",
    "DISK_NAME",
    "MANIFEST_NAME",
    "STATE_NAME",
    "XML_NAME",
    "WarmCache",
    "WarmManifest",
    "WarmTemplate",
    "hardware_of",
    "port_is_free",
    "template_name",
]

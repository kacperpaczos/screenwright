"""Import katalogów zebranych z wnętrza gości (Ansible ``collect-catalog``) do korpusu.

Kolektory (``collector-<distro>``) nie parsują niczego: role Ansible instalują
narzędzia sklepów, odświeżają katalogi i ``fetch``-ują surowe pliki na hosta —
``corpus/guest/<distro>/<host>/<ścieżka-w-gościu>``. Tu rozpoznajemy format po
ścieżce i oddajemy plik tym samym parserom, których używają kolektory z
publicznych endpointów (``iter_appstream_entries``, ``iter_dep11_entries``),
z ``source=guest-*`` — bo to jest ten sam AppStream/DEP-11, tylko widziany od
środka dystrybucji (priorytety katalogów, wersje, stan po podmianie).

Rozpoznanie formatu:

- ``/var/lib/flatpak/appstream/<remote>/<arch>/active/appstream.xml.gz`` →
  ``guest-flatpak`` (remote w ``notes``),
- ``*dep11_Components-<arch>.yml.gz`` (apt) → ``guest-dep11``,
- pozostałe ``*.xml.gz`` (``/usr/share/swcatalog/xml``, ``/var/lib/swcatalog``) →
  ``guest-appstream``,
- ``snap-find.tgz`` / ``find-<kategoria>.json`` (snapd ``/v2/find``) → ``guest-snapd``.
"""

from __future__ import annotations

import gzip
import json
import tarfile
from collections.abc import Iterable, Iterator  # noqa: TC003 (Iterable at runtime via signatures)
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from xml.etree.ElementTree import fromstring

import yaml
from pydantic import BaseModel, ConfigDict, Field
from shared.http_client import HttpClient  # noqa: TC002 (used at runtime default in hydrate_media)
from shared.logging import log_entry
from shared.media import fetch_to_corpus
from shared.pydantic_utils import strict_validate
from shared.types import AppId, HttpUrl, Sha256

from domains.corpus.index import IndexWriter  # noqa: TC001
from domains.corpus.models import CorpusEntry
from domains.corpus.sources.fedora import DEFAULT_HEIGHT, DEFAULT_WIDTH, iter_appstream_entries
from domains.corpus.sources.snap import SnapMediaItem  # noqa: TC001 (pydantic field type)
from domains.corpus.sources.ubuntu_dep11 import iter_dep11_entries

GUEST_SOURCES = ("guest-appstream", "guest-dep11", "guest-flatpak", "guest-snapd")


@dataclass(frozen=True)
class GuestCatalog:
    path: Path
    source: str
    notes: str | None = None


def classify(path: Path) -> GuestCatalog | None:
    """Format katalogu po ścieżce z gościa (albo po nazwie, gdy fetch był płaski)."""
    posix = path.as_posix()
    name = path.name
    if name == "snap-find.tgz" or (name.startswith("find-") and name.endswith(".json")):
        return GuestCatalog(path, "guest-snapd")
    if name.endswith(".yml.gz") and "dep11" in name:
        return GuestCatalog(path, "guest-dep11")
    if "/flatpak/appstream/" in posix:
        remote = posix.split("/flatpak/appstream/", 1)[1].split("/", 1)[0]
        return GuestCatalog(path, "guest-flatpak", f"remote={remote}")
    if name == "appstream.xml.gz":
        return GuestCatalog(path, "guest-flatpak")
    if name.endswith(".xml.gz"):
        return GuestCatalog(path, "guest-appstream")
    return None


def discover(guest_dir: Path, distro: str) -> list[GuestCatalog]:
    root = guest_dir / distro
    if not root.is_dir():
        return []
    found = [c for p in sorted(root.rglob("*")) if p.is_file() and (c := classify(p)) is not None]
    return found


class _SnapFindSnap(BaseModel):
    model_config = ConfigDict(extra="ignore")

    name: str
    id: str | None = None
    media: list[SnapMediaItem] = Field(default_factory=list)


class _SnapFindResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    result: list[_SnapFindSnap] = Field(default_factory=list)


def _snap_find_payloads(path: Path) -> Iterator[tuple[str, bytes]]:
    if path.suffix == ".json":
        yield path.name, path.read_bytes()
        return
    with tarfile.open(path) as tar:
        for member in tar.getmembers():
            if member.isfile() and member.name.endswith(".json") and "find-" in member.name:
                handle = tar.extractfile(member)
                if handle is not None:
                    yield member.name, handle.read()


def _iter_snapd_entries(
    catalog: GuestCatalog, *, distro: str, apps: set[str] | None
) -> Iterator[dict[str, object]]:
    now = datetime.now(UTC)
    for member_name, payload in _snap_find_payloads(catalog.path):
        try:
            response = strict_validate(_SnapFindResponse, json.loads(payload))
        except Exception as exc:
            log_entry(20, "corpus.guest.snapd_parse_error", file=member_name, error=str(exc))
            continue
        for snap in response.result:
            if apps is not None and snap.name not in apps:
                continue
            for item in snap.media:
                if item.type != "screenshot":
                    continue
                width = item.width or DEFAULT_WIDTH
                height = item.height or DEFAULT_HEIGHT
                notes = f"snap-id={snap.id}" if snap.id else None
                if item.width is None or item.height is None:
                    notes = f"{notes};dims=unknown" if notes else "dims=unknown"
                try:
                    entry = CorpusEntry(
                        app_id=AppId(snap.name),
                        distro=distro,
                        source="guest-snapd",
                        source_url=HttpUrl(item.url),
                        kind="source",
                        width=width,
                        height=height,
                        fetched=now,
                        sha256=Sha256("0" * 64),
                        file="media/unfetched.png",
                        notes=notes,
                    )
                except Exception as exc:
                    log_entry(20, "corpus.guest.entry_invalid", app=snap.name, error=str(exc))
                    continue
                yield entry.model_dump(mode="json")


# Flathub i Snap Store są wspólne dla dystrybucji — zrzuty przychodzą z jednego,
# scentralizowanego kanału niezależnie od tego, na której maszynie je zebrano.
# Dlatego dostają własny kubełek `distro`, a nie kubełek kolektora (inaczej
# deduplikacja po URL scaliłaby je pod dystrybucję, która trafiła pierwsza).
_SOURCE_DISTRO = {"guest-flatpak": "flathub", "guest-snapd": "snap"}


def entry_distro(collector_distro: str, source: str) -> str:
    """Kubełek `distro` wpisu: flathub/snap dla platform wspólnych, inaczej dystrybucja kolektora."""
    return _SOURCE_DISTRO.get(source, collector_distro)


def iter_catalog_entries(
    catalog: GuestCatalog, *, distro: str, apps: set[str] | None = None
) -> Iterator[dict[str, object]]:
    """Wpisy korpusu z jednego pliku katalogu; parser wybierany po ``catalog.source``."""
    if catalog.source in ("guest-appstream", "guest-flatpak"):
        with gzip.open(catalog.path, "rb") as fh:
            root = fromstring(fh.read())
        yield from iter_appstream_entries(
            root, distro=distro, source=catalog.source, apps=apps, notes=catalog.notes
        )
    elif catalog.source == "guest-dep11":
        with gzip.open(catalog.path, "rb") as fh:
            docs: list[Any] = list(yaml.safe_load_all(fh))
        yield from iter_dep11_entries(
            docs, distro=distro, source="guest-dep11", apps=apps, notes=catalog.notes
        )
    elif catalog.source == "guest-snapd":
        yield from _iter_snapd_entries(catalog, distro=distro, apps=apps)


def import_guest(
    guest_dir: Path,
    writer: IndexWriter,
    *,
    distros: Iterable[str] | None = None,
    apps: Iterable[str] | None = None,
    download_media: bool = False,
    max_media: int | None = None,
    client: HttpClient | None = None,
    dry_run: bool = False,
) -> dict[str, int]:
    """Dopisuje do indeksu wszystko, co leży w ``guest_dir/<distro>/``.

    Zwraca liczniki ``"<distro>:<source>" -> nowe wpisy``. Duplikaty
    (ten sam URL dla tej samej aplikacji i źródła) są pomijane — także te, które
    już są w indeksie, więc import jest idempotentny. Media pobierane są na
    hoście (``shared.media.fetch_to_corpus``) tylko dla pierwszych ``max_media``
    wpisów, bo katalog całej dystrybucji to tysiące plików.
    """
    wanted_distros = (
        sorted(distros)
        if distros is not None
        else sorted(p.name for p in guest_dir.iterdir() if p.is_dir())
    )
    app_filter = {a.removesuffix(".desktop") for a in apps} if apps is not None else None
    existing = {(e.source_url, e.app_id, e.source) for e in writer.entries}
    seen: set[tuple[object, object, object]] = set()
    counts: dict[str, int] = {}
    collected: list[tuple[str, dict[str, object]]] = []
    for distro in wanted_distros:
        catalogs = discover(guest_dir, distro)
        if not catalogs:
            log_entry(30, "corpus.guest.nothing_found", distro=distro, guest_dir=str(guest_dir))
            continue
        for catalog in catalogs:
            bucket = entry_distro(distro, catalog.source)
            for raw in iter_catalog_entries(catalog, distro=bucket, apps=app_filter):
                key = (raw["source_url"], raw["app_id"], raw["source"])
                if key in seen or key in existing:
                    continue
                seen.add(key)
                collected.append((f"{distro}:{catalog.source}", raw))
    if download_media and not dry_run and collected:
        limit = len(collected) if max_media is None else max(0, max_media)
        head = [raw for _, raw in collected[:limit]]
        fetched = fetch_to_corpus(head, writer.root, client=client)
        collected = [
            (label, fetched[i]) for i, (label, _) in enumerate(collected[:limit])
        ] + collected[limit:]
    for label, raw in collected:
        try:
            entry = strict_validate(CorpusEntry, raw)
        except Exception as exc:
            log_entry(20, "corpus.guest.entry_invalid", error=str(exc), label=label)
            continue
        if not dry_run:
            writer.append(entry)
        counts[label] = counts.get(label, 0) + 1
    if not dry_run:
        writer.flush()
    log_entry(20, "corpus.guest.imported", counts=counts)
    return counts


def hydrate_media(
    writer: IndexWriter,
    *,
    limit: int | None = None,
    sources: Iterable[str] | None = None,
    kinds: Iterable[str] = ("source",),
    per_app: int | None = None,
    client: HttpClient | None = None,
) -> int:
    """Pobiera bajty obrazów dla wpisów już w indeksie (te z ``media/unfetched.png``).

    Import z gości zapisuje same URL-e; tu ściągamy pliki na hosta i podmieniamy
    w indeksie ``sha256`` + ``file`` (reszta wpisu bez zmian). ``sources``/``kinds``
    zawężają, ``per_app`` ogranicza liczbę zdjęć na aplikację (rozrzut do galerii),
    ``limit`` — łącznie. Zwraca liczbę pobranych plików. Idempotentne: wpis z realnym
    ``sha256`` jest pomijany, a ``fetch_to_corpus`` nie powiela istniejących plików.
    """
    source_set = set(sources) if sources is not None else None
    kind_set = set(kinds)
    picked: list[int] = []
    per_app_count: dict[str, int] = {}
    for idx, entry in enumerate(writer.entries):
        if entry.file != Path("media/unfetched.png") or entry.sha256 != Sha256("0" * 64):
            continue
        if source_set is not None and entry.source not in source_set:
            continue
        if entry.kind not in kind_set:
            continue
        if per_app is not None:
            if per_app_count.get(entry.app_id, 0) >= per_app:
                continue
            per_app_count[entry.app_id] = per_app_count.get(entry.app_id, 0) + 1
        picked.append(idx)
        if limit is not None and len(picked) >= limit:
            break
    if not picked:
        return 0
    entries = writer.entries
    raw = [entries[i].model_dump(mode="json") for i in picked]
    fetched = fetch_to_corpus(raw, writer.root, client=client)
    done = 0
    for i, updated in zip(picked, fetched, strict=True):
        if updated.get("file") == "media/unfetched.png":
            continue
        entries[i] = entries[i].model_copy(
            update={"sha256": Sha256(str(updated["sha256"])), "file": str(updated["file"])}
        )
        done += 1
    writer.replace_all(entries)
    writer.flush()
    log_entry(20, "corpus.guest.hydrated", downloaded=done, requested=len(picked))
    return done


__all__ = [
    "GUEST_SOURCES",
    "GuestCatalog",
    "classify",
    "discover",
    "entry_distro",
    "hydrate_media",
    "import_guest",
    "iter_catalog_entries",
]

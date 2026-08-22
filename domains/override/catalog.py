"""Logika budowania override'a katalogu AppStream."""

import gzip
from pathlib import Path
from typing import Any
from xml.etree.ElementTree import (
    Element,
    ElementTree,
    fromstring,
    indent,
    register_namespace,
    tostring,
)

import yaml
from shared.logging import log_entry

from domains.override.models import CatalogPatchResult, OverrideResult, OverrideSpec
from domains.override.ports import CatalogLoader, ComponentFinder

APPSTREAM_NS = "http://appstream.org/"
# Aby zserializowany namespaced katalog wracał jako <components xmlns="…">,
# a nie z prefiksem ns0:. Bezpieczne dla katalogów bez namespace (no-op).
register_namespace("", APPSTREAM_NS)

THUMBNAILS = [(752, 423), (624, 351), (224, 126), (112, 63)]
COMPONENT_NS = {"c": "http://appstream.org/"}


class GzipXmlCatalogLoader:
    """Loader XML z obsługą .gz i plain."""

    def load(self, path: Path) -> bytes:
        if path.suffix == ".gz":
            with gzip.open(path, "rb") as fh:
                return fh.read()
        return path.read_bytes()


class ElementTreeComponentFinder:
    """Szuka komponentu w katalogu AppStream.

    Próbuje obu form: z namespace (AppStream ≥1.0 z appstream-generator)
    i bez (legacy / metainfo-driven).
    """

    def find(self, payload: bytes, component_id: str) -> bytes | None:
        from xml.etree.ElementTree import indent, tostring

        root = fromstring(payload)
        for component in root:
            cid = _first_child(component, "id")
            if cid is not None and cid.text == component_id:
                indent(component, space="  ")
                result: bytes = tostring(component, encoding="utf-8")
                return result
        return None


def _first_child(component: Element, name: str) -> Element | None:
    """Pierwsze dziecko o podanej nazwie — z namespace lub bez."""
    direct = component.find(name)
    if direct is not None:
        return direct
    return component.find(f"c:{name}", COMPONENT_NS)


def _strip_screenshots(component: Element) -> int:
    """Usuwa wszystkie bloki <screenshots> (z NS i bez). Zwraca ile usunięto."""
    removed = 0
    for tag in ("screenshots", f"{{{APPSTREAM_NS}}}screenshots"):
        for old in component.findall(tag):
            component.remove(old)
            removed += 1
    for old in component.findall("c:screenshots", COMPONENT_NS):
        component.remove(old)
        removed += 1
    return removed


def _ns_prefix(element: Element) -> str:
    """Zwraca '{uri}' jeśli element jest w namespace, inaczej ''."""
    tag = element.tag
    if isinstance(tag, str) and tag.startswith("{"):
        return tag[: tag.index("}") + 1]
    return ""


def build_override(
    spec: OverrideSpec,
    *,
    loader: CatalogLoader,
    finder: ComponentFinder,
) -> OverrideResult:
    width, height = spec.source_size
    component_xml: bytes | None = None
    for catalog in spec.catalog_paths:
        try:
            payload = loader.load(catalog)
        except OSError as exc:
            log_entry(20, "override.catalog_unreadable", path=str(catalog), error=str(exc))
            continue
        candidate = finder.find(payload, spec.component_id)
        if candidate is not None:
            component_xml = candidate
            log_entry(20, "override.component_found", path=str(catalog), id=spec.component_id)
            break
    if component_xml is None:
        raise LookupError(f"component {spec.component_id} not found")

    component = fromstring(component_xml)
    removed = _strip_screenshots(component)
    component.append(_build_screenshots(spec.base_url, spec.prefix, spec.caption, width, height))

    root = Element(
        "components",
        {
            "origin": spec.origin,
            "version": "0.14",
            "priority": str(spec.priority),
        },
    )
    root.append(component)
    indent(root, space="  ")
    spec.out.parent.mkdir(parents=True, exist_ok=True)
    ElementTree(root).write(spec.out, encoding="UTF-8", xml_declaration=True)

    return OverrideResult(
        out_path=spec.out,
        origin=spec.origin,
        priority=spec.priority,
        replaced_screenshots=removed,
    )


def _build_screenshots(
    base_url: str, prefix: str, caption: str, width: int, height: int, ns: str = ""
) -> Element:
    shots = Element(f"{ns}screenshots")
    shot = Element(f"{ns}screenshot", {"type": "default"})
    cap = Element(f"{ns}caption")
    cap.text = caption
    shot.append(cap)
    src = Element(f"{ns}image", {"type": "source", "width": str(width), "height": str(height)})
    src.text = f"{base_url.rstrip('/')}/{prefix}-source.png"
    shot.append(src)
    for w, h in THUMBNAILS:
        thumb = Element(f"{ns}image", {"type": "thumbnail", "width": str(w), "height": str(h)})
        thumb.text = f"{base_url.rstrip('/')}/{prefix}-{w}x{h}.png"
        shot.append(thumb)
    shots.append(shot)
    return shots


def _is_dep11(payload: bytes) -> bool:
    """DEP-11 (Ubuntu/Debian) to YAML; AppStream Fedory to XML."""
    head = payload.lstrip()[:200]
    if head.startswith(b"<"):
        return False
    return b"DEP-11" in payload[:400] or head.startswith(b"---") or head.startswith(b"File:")


def _build_dep11_screenshot(
    base_url: str, prefix: str, caption: str, width: int, height: int
) -> dict[str, Any]:
    """Blok Screenshots[0] w kształcie DEP-11 (URL-e absolutne → MediaBaseUrl pomijany)."""
    base = base_url.rstrip("/")
    return {
        "default": True,
        "caption": {"C": caption},
        "source-image": {"url": f"{base}/{prefix}-source.png", "width": width, "height": height},
        "thumbnails": [
            {"url": f"{base}/{prefix}-{w}x{h}.png", "width": w, "height": h} for w, h in THUMBNAILS
        ],
    }


def _patch_dep11(
    payload: bytes, spec: OverrideSpec, width: int, height: int
) -> tuple[bytes, int] | None:
    """Podmienia Screenshots komponentu w wielodokumentowym DEP-11 YAML.

    Zwraca (bajty gz-owalne, ile bloków podmieniono) albo None, gdy komponentu
    o danym ID nie ma w tym pliku.
    """
    docs = list(yaml.safe_load_all(payload.decode("utf-8", errors="replace")))
    replaced = 0
    for doc in docs:
        if isinstance(doc, dict) and doc.get("ID") == spec.component_id:
            replaced += len(doc.get("Screenshots", []) or [])
            doc["Screenshots"] = [
                _build_dep11_screenshot(spec.base_url, spec.prefix, spec.caption, width, height)
            ]
    if not any(isinstance(d, dict) and d.get("ID") == spec.component_id for d in docs):
        return None
    out = yaml.safe_dump_all(
        docs, default_flow_style=False, allow_unicode=True, sort_keys=False
    ).encode("utf-8")
    return out, replaced


def patch_catalog(
    spec: OverrideSpec,
    *,
    loader: CatalogLoader,
) -> CatalogPatchResult:
    """Podmienia zrzuty komponentu W SAMYM katalogu bazowym (in-place).

    W przeciwieństwie do :func:`build_override` (osobny plik z priorytetem, który
    libappstream tylko UNIONuje ze zrzutami bazy), tu przepisujemy blok zrzutów
    docelowego komponentu wewnątrz katalogu i zapisujemy CAŁY katalog z powrotem.
    Dzięki temu `appstreamcli dump` zwraca DOKŁADNIE nasz zrzut, a sklep renderuje
    nasz obraz zamiast oryginału. Weryfikowane na żywo 2026-08-22 (GNOME Software
    50 i KDE Discover na Fedorze — katalog XML).

    Obsługuje oba formaty katalogu: **AppStream XML** (rpm/Fedora, `<screenshots>`)
    i **DEP-11 YAML** (deb/Ubuntu, `Screenshots:`) — format wykrywany po treści.
    Czyta pierwszy odczytywalny katalog z ``spec.catalog_paths`` zawierający
    komponent i zapisuje wynik do ``spec.out`` (gz, gdy rozszerzenie ``.gz``).
    ``spec.out`` może wskazywać na ten sam plik co źródło (podmiana w miejscu).
    """
    width, height = spec.source_size
    for catalog in spec.catalog_paths:
        try:
            payload = loader.load(catalog)
        except OSError as exc:
            log_entry(20, "override.catalog_unreadable", path=str(catalog), error=str(exc))
            continue

        if _is_dep11(payload):
            result = _patch_dep11(payload, spec, width, height)
            if result is None:
                continue
            data, removed = result
        else:
            candidate_root = fromstring(payload)
            target = next(
                (
                    c
                    for c in candidate_root
                    if (cid := _first_child(c, "id")) is not None and cid.text == spec.component_id
                ),
                None,
            )
            if target is None:
                continue
            ns = _ns_prefix(target)
            removed = _strip_screenshots(target)
            target.append(
                _build_screenshots(spec.base_url, spec.prefix, spec.caption, width, height, ns=ns)
            )
            indent(candidate_root, space="  ")
            data = tostring(candidate_root, encoding="UTF-8", xml_declaration=True)

        log_entry(20, "override.patch_component_found", path=str(catalog), id=spec.component_id)
        spec.out.parent.mkdir(parents=True, exist_ok=True)
        if spec.out.suffix == ".gz":
            with gzip.open(spec.out, "wb") as fh:
                fh.write(data)
        else:
            spec.out.write_bytes(data)
        return CatalogPatchResult(
            out_path=spec.out,
            catalog_path=catalog,
            component_id=spec.component_id,
            replaced_screenshots=removed,
        )

    raise LookupError(
        f"component {spec.component_id} not found in {[str(p) for p in spec.catalog_paths]}"
    )


__all__ = [
    "ElementTreeComponentFinder",
    "GzipXmlCatalogLoader",
    "build_override",
    "patch_catalog",
]

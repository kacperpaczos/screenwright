"""Logika budowania override'a katalogu AppStream."""

import gzip
from pathlib import Path
from xml.etree.ElementTree import Element, ElementTree, fromstring, indent

from shared.logging import log_entry

from domains.override.models import OverrideResult, OverrideSpec
from domains.override.ports import CatalogLoader, ComponentFinder

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
    for tag in ("screenshots", "{http://appstream.org/}screenshots"):
        for old in component.findall(tag):
            component.remove(old)
            removed += 1
    for old in component.findall("c:screenshots", COMPONENT_NS):
        component.remove(old)
        removed += 1
    return removed


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
    base_url: str, prefix: str, caption: str, width: int, height: int
) -> Element:
    shots = Element("screenshots")
    shot = Element("screenshot", {"type": "default"})
    cap = Element("caption")
    cap.text = caption
    shot.append(cap)
    src = Element("image", {"type": "source", "width": str(width), "height": str(height)})
    src.text = f"{base_url.rstrip('/')}/{prefix}-source.png"
    shot.append(src)
    for w, h in THUMBNAILS:
        thumb = Element("image", {"type": "thumbnail", "width": str(w), "height": str(h)})
        thumb.text = f"{base_url.rstrip('/')}/{prefix}-{w}x{h}.png"
        shot.append(thumb)
    shots.append(shot)
    return shots


__all__ = [
    "ElementTreeComponentFinder",
    "GzipXmlCatalogLoader",
    "build_override",
]

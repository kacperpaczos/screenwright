"""Diagnostyka snap-store w VM Ubuntu (parser JSON).

Wywoływany przez ``vm/scripts/diagnose-ubuntu.sh`` z surowym wyjściem SSH na
stdin. Format wejściowy to sekcje oddzielone markerami::

    ===SECTION:<name>===
    ...dowolna zawartość...
    ===END_SECTION===

Wynik: JSON na stdout zgodny z planem M2 §1
(``docs/snap-store-diagnostics.md``).
"""

from __future__ import annotations

import json
import re
import sys
from typing import Any

_SECTION_START = re.compile(r"^===SECTION:(?P<name>[a-zA-Z0-9_-]+)===\s*$")
_SECTION_END = re.compile(r"^===END_SECTION===\s*$")

_SNAPD_VERSION_RE = re.compile(r"snap\s+(\d+\.\d+\.\d+)", re.MULTILINE)
_IPV4_RE = re.compile(r"\b(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})\b")
_API_URL_RE = re.compile(r"https?://api\.snapcraft\.io[\w./?=&-]*")

# Media (screenshoty, ikony, banery) NIE leżą na api.snapcraft.io — snapd
# oddaje URL-e na dashboard.snapcraft.io. Szukanie ich wzorcem `_API_URL_RE`
# nie mogło zadziałać: łapało wyłącznie linki do plików .snap.
_MEDIA_URL_RE = re.compile(r"https?://[\w.-]*snapcraft\.io/site_media/[^\"'\s\\]+")


def parse(raw: str) -> dict[str, Any]:
    sections = _split_sections(raw)
    snapd_version = _extract_snapd_version(sections.get("snapd_version", ""))
    store_info = sections.get("snap_store_info", "")
    cache_files = sections.get("snap_store_cache", "")
    api_endpoints = _extract_api_endpoints(sections.get("snapd_journal", ""))
    api_endpoints += _extract_api_endpoints(sections.get("api_probe", ""))
    media_probe = sections.get("media_probe", "")
    return {
        "snapd_version": snapd_version,
        "snap_store_channel": _extract_field(store_info, "tracking", default=""),
        "snap_store_version": _extract_field(store_info, "version", default=""),
        "api_endpoints": sorted(set(api_endpoints)),
        "cache_file_count": _count_files(cache_files),
        # URL-e do plików .snap i innych zasobów api.snapcraft.io. NIE są to
        # screenshoty — patrz docs/snap-store-diagnostics.md.
        "media_url_hints": _extract_api_endpoints(media_probe),
        "screenshot_urls": _extract_screenshot_urls(media_probe),
        "raw": sections,
    }


def _split_sections(raw: str) -> dict[str, str]:
    sections: dict[str, list[str]] = {}
    current: str | None = None
    for line in raw.splitlines():
        m_start = _SECTION_START.match(line)
        if m_start:
            current = m_start.group("name")
            sections[current] = []
            continue
        if _SECTION_END.match(line):
            current = None
            continue
        if current is not None:
            sections[current].append(line)
    return {name: "\n".join(lines) for name, lines in sections.items()}


def _extract_snapd_version(text: str) -> str:
    m = _SNAPD_VERSION_RE.search(text)
    return m.group(1) if m else ""


def _extract_field(text: str, key: str, default: str = "") -> str:
    m = re.search(rf"(?m)^{re.escape(key)}:\s*(?P<v>.+?)\s*$", text)
    return m.group("v").strip() if m else default


def _extract_api_endpoints(text: str) -> list[str]:
    return list({m.group(0) for m in _API_URL_RE.finditer(text)})


def _extract_screenshot_urls(text: str) -> list[str]:
    """URL-e screenshotów z odpowiedzi store API.

    Najpierw próbujemy sparsować JSON i wziąć ``snap.media[type == screenshot]``
    — tylko to daje pewność, że URL jest screenshotem, a nie ikoną czy banerem
    (wszystkie trzy leżą pod tym samym prefiksem ``/site_media/``). Gdy ciało
    jest ucięte albo to nie JSON, spadamy na regex po całym tekście.
    """
    stripped = text.strip()
    if stripped.startswith("{"):
        try:
            payload = json.loads(stripped)
        except json.JSONDecodeError:
            pass
        else:
            media = payload.get("snap", {}).get("media", [])
            urls = [
                str(entry["url"])
                for entry in media
                if isinstance(entry, dict)
                and entry.get("type") == "screenshot"
                and entry.get("url")
            ]
            return sorted(set(urls))
    return sorted({m.group(0) for m in _MEDIA_URL_RE.finditer(text)})


def _count_files(text: str) -> int:
    return sum(1 for line in text.splitlines() if line.strip())


def main(argv: list[str]) -> int:
    if len(argv) != 1:
        print("usage: diagnose_ubuntu.py <raw-ssh-output-file>", file=sys.stderr)
        return 2
    if argv[0] == "-":
        raw = sys.stdin.read()
    else:
        with open(argv[0], encoding="utf-8") as f:
            raw = f.read()
    parsed = parse(raw)
    json.dump(parsed, sys.stdout, indent=2, sort_keys=True)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))


__all__ = ["main", "parse"]

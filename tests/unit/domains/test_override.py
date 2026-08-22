"""Testy jednostkowe — OverrideSpec, build_override (z adapterami in-memory)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from domains.override.catalog import (
    ElementTreeComponentFinder,
    GzipXmlCatalogLoader,
    build_override,
)
from domains.override.models import OverrideResult, OverrideSpec
from pydantic import ValidationError


def _valid_spec(**overrides: Any) -> OverrideSpec:
    base: dict[str, Any] = {
        "component_id": "org.kde.kcalc.desktop",
        "base_url": "http://127.0.0.1:8899",
        "prefix": "kcalc",
        "out": Path("/tmp/90-screenwright.xml"),
        "origin": "screenwright",
        "priority": 1,
    }
    base.update(overrides)
    return OverrideSpec(**base)


class TestOverrideSpec:
    def test_default(self) -> None:
        spec = _valid_spec()
        assert spec.priority == 1
        assert spec.source_size == (640, 480)
        assert spec.catalog_paths == [Path("/usr/share/swcatalog/xml/fedora.xml.gz")]

    def test_priority_zero_rejected(self) -> None:
        with pytest.raises(ValidationError):
            _valid_spec(priority=0)

    def test_prefix_pattern(self) -> None:
        with pytest.raises(ValidationError):
            _valid_spec(prefix="BAD PREFIX")

    def test_extra_forbidden(self) -> None:
        with pytest.raises(ValidationError):
            OverrideSpec.model_validate(
                {
                    "component_id": "x",
                    "base_url": "http://x/",
                    "prefix": "x",
                    "out": "x",
                    "extra": 1,
                }
            )


class TestBuildOverride:
    _CATALOG_XML = """<?xml version='1.0'?>
<components origin="fedora" version="0.14">
  <component>
    <id>org.kde.kcalc.desktop</id>
    <name>KCalc</name>
    <pkgname>kcalc</pkgname>
    <screenshots>
      <screenshot type="default">
        <image type="source" width="800" height="600">https://upstream/source.png</image>
      </screenshot>
    </screenshots>
  </component>
  <component>
    <id>org.gimp.GIMP.desktop</id>
    <name>GIMP</name>
  </component>
</components>
"""

    def test_replaces_screenshots(self, tmp_path: Path) -> None:
        import gzip

        catalog = tmp_path / "fedora.xml.gz"
        with gzip.open(catalog, "wb") as fh:
            fh.write(TestBuildOverride._CATALOG_XML.encode("utf-8"))
        out = tmp_path / "out.xml"
        spec = _valid_spec(catalog_paths=[catalog], out=out)
        result = build_override(
            spec, loader=GzipXmlCatalogLoader(), finder=ElementTreeComponentFinder()
        )
        assert isinstance(result, OverrideResult)
        assert result.replaced_screenshots == 1
        assert result.out_path == out
        text = out.read_text(encoding="utf-8")
        assert "127.0.0.1:8899/kcalc-source.png" in text
        assert "127.0.0.1:8899/kcalc-752x423.png" in text
        assert "org.kde.kcalc.desktop" in text
        assert "GIMP" not in text
        assert "https://upstream/source.png" not in text, (
            f"old screenshot URL must be removed; got:\n{text}"
        )
        assert text.count("<screenshots>") == 1
        assert text.count("</screenshots>") == 1

    def test_component_not_found_raises(self, tmp_path: Path) -> None:
        catalog = tmp_path / "empty.xml.gz"
        catalog.write_bytes(b"<components/>")
        spec = _valid_spec(
            component_id="nonexistent.desktop",
            catalog_paths=[catalog],
            out=tmp_path / "out.xml",
        )
        with pytest.raises(LookupError):
            build_override(spec, loader=GzipXmlCatalogLoader(), finder=ElementTreeComponentFinder())

    def test_priority_in_output(self, tmp_path: Path) -> None:
        import gzip

        catalog = tmp_path / "fedora.xml.gz"
        with gzip.open(catalog, "wb") as fh:
            fh.write(TestBuildOverride._CATALOG_XML.encode("utf-8"))
        out = tmp_path / "out.xml"
        spec = _valid_spec(catalog_paths=[catalog], out=out, priority=10)
        build_override(spec, loader=GzipXmlCatalogLoader(), finder=ElementTreeComponentFinder())
        text = out.read_text(encoding="utf-8")
        assert 'priority="10"' in text

    _NAMESPACED_CATALOG = """<?xml version='1.0'?>
<components xmlns="http://appstream.org/" origin="fedora" version="0.14">
  <component>
    <id>org.gimp.GIMP.desktop</id>
    <name>GIMP</name>
    <screenshots>
      <screenshot type="default">
        <image type="source" width="1280" height="720">https://upstream/gimp.png</image>
      </screenshot>
    </screenshots>
  </component>
</components>
"""

    def test_namespaced_catalog_replaces_screenshots(self, tmp_path: Path) -> None:
        """Real Fedora appstream-generator output uses default namespace."""
        import gzip

        catalog = tmp_path / "fedora-namespaced.xml.gz"
        with gzip.open(catalog, "wb") as fh:
            fh.write(self._NAMESPACED_CATALOG.encode("utf-8"))
        out = tmp_path / "out.xml"
        spec = _valid_spec(
            component_id="org.gimp.GIMP.desktop",
            prefix="gimp",
            catalog_paths=[catalog],
            out=out,
        )
        result = build_override(
            spec, loader=GzipXmlCatalogLoader(), finder=ElementTreeComponentFinder()
        )
        assert result.replaced_screenshots == 1
        text = out.read_text(encoding="utf-8")
        assert "https://upstream/gimp.png" not in text
        assert "127.0.0.1:8899/gimp-source.png" in text
        assert text.count("<screenshots>") == 1


class TestPatchCatalog:
    """patch_catalog — podmiana zrzutów W SAMYM katalogu bazowym (in-place).

    Odróżnia się od build_override tym, że zachowuje POZOSTAŁE komponenty
    (build_override zapisuje tylko jeden komponent w nowym <components>).
    """

    _CATALOG_XML = """<?xml version='1.0'?>
<components origin="fedora" version="0.8">
  <component type="desktop">
    <id>org.kde.kcalc.desktop</id>
    <name>KCalc</name>
    <screenshots>
      <screenshot type="default">
        <image type="source" width="800" height="600">https://upstream/source.png</image>
        <image type="thumbnail" width="624" height="351">https://upstream/thumb.png</image>
      </screenshot>
    </screenshots>
  </component>
  <component type="desktop">
    <id>org.gimp.GIMP.desktop</id>
    <name>GIMP</name>
    <screenshots>
      <screenshot type="default">
        <image type="source" width="1">https://gimp/keep.png</image>
      </screenshot>
    </screenshots>
  </component>
</components>
"""

    _NAMESPACED_XML = """<?xml version='1.0'?>
<components xmlns="http://appstream.org/" origin="fedora" version="0.8">
  <component type="desktop">
    <id>org.kde.kcalc.desktop</id>
    <screenshots>
      <screenshot type="default">
        <image type="source" width="800" height="600">https://upstream/source.png</image>
      </screenshot>
    </screenshots>
  </component>
</components>
"""

    def _catalog(self, tmp_path: Path, xml: str, name: str = "fedora.xml.gz") -> Path:
        import gzip

        catalog = tmp_path / name
        with gzip.open(catalog, "wb") as fh:
            fh.write(xml.encode("utf-8"))
        return catalog

    def test_replaces_screenshots_in_place(self, tmp_path: Path) -> None:
        from domains.override.catalog import patch_catalog
        from domains.override.models import CatalogPatchResult

        catalog = self._catalog(tmp_path, self._CATALOG_XML)
        out = tmp_path / "out.xml"
        spec = _valid_spec(catalog_paths=[catalog], out=out)
        result = patch_catalog(spec, loader=GzipXmlCatalogLoader())
        assert isinstance(result, CatalogPatchResult)
        assert result.replaced_screenshots == 1
        assert result.catalog_path == catalog
        text = out.read_text(encoding="utf-8")
        # nasze URL-e obecne, oryginalny zrzut KCalc usunięty
        assert "127.0.0.1:8899/kcalc-source.png" in text
        assert "127.0.0.1:8899/kcalc-624x351.png" in text
        assert "https://upstream/source.png" not in text
        assert "https://upstream/thumb.png" not in text

    def test_preserves_other_components(self, tmp_path: Path) -> None:
        """Cecha odróżniająca od build_override: reszta katalogu zostaje nietknięta."""
        from domains.override.catalog import patch_catalog

        catalog = self._catalog(tmp_path, self._CATALOG_XML)
        out = tmp_path / "out.xml"
        spec = _valid_spec(catalog_paths=[catalog], out=out)
        patch_catalog(spec, loader=GzipXmlCatalogLoader())
        text = out.read_text(encoding="utf-8")
        # GIMP i jego zrzut MUSZĄ przetrwać (build_override by je usunął)
        assert "org.gimp.GIMP.desktop" in text
        assert "https://gimp/keep.png" in text
        # dokładnie tyle bloków <screenshots> ile komponentów (2)
        assert text.count("<screenshots>") == 2

    def test_in_place_same_file(self, tmp_path: Path) -> None:
        """out == źródło: podmiana w miejscu, wynik czytelny ponownie."""
        import gzip

        from domains.override.catalog import patch_catalog

        catalog = self._catalog(tmp_path, self._CATALOG_XML)
        spec = _valid_spec(catalog_paths=[catalog], out=catalog)
        patch_catalog(spec, loader=GzipXmlCatalogLoader())
        with gzip.open(catalog) as fh:
            text = fh.read().decode("utf-8")
        assert "127.0.0.1:8899/kcalc-source.png" in text
        assert "https://upstream/source.png" not in text
        assert "org.gimp.GIMP.desktop" in text

    def test_writes_gzip_when_out_has_gz_suffix(self, tmp_path: Path) -> None:
        import gzip

        from domains.override.catalog import patch_catalog

        catalog = self._catalog(tmp_path, self._CATALOG_XML)
        out = tmp_path / "patched.xml.gz"
        spec = _valid_spec(catalog_paths=[catalog], out=out)
        patch_catalog(spec, loader=GzipXmlCatalogLoader())
        with gzip.open(out) as fh:
            text = fh.read().decode("utf-8")
        assert "127.0.0.1:8899/kcalc-source.png" in text

    def test_namespaced_catalog_round_trips(self, tmp_path: Path) -> None:
        from domains.override.catalog import patch_catalog

        catalog = self._catalog(tmp_path, self._NAMESPACED_XML, name="ns.xml.gz")
        out = tmp_path / "out.xml"
        spec = _valid_spec(catalog_paths=[catalog], out=out)
        patch_catalog(spec, loader=GzipXmlCatalogLoader())
        text = out.read_text(encoding="utf-8")
        # namespace zachowany jako default xmlns, nasze URL-e w tym namespace
        assert 'xmlns="http://appstream.org/"' in text
        assert "127.0.0.1:8899/kcalc-source.png" in text
        assert "https://upstream/source.png" not in text
        # brak brzydkich prefiksów ns0:
        assert "ns0:" not in text

    def test_component_not_found_raises(self, tmp_path: Path) -> None:
        from domains.override.catalog import patch_catalog

        catalog = self._catalog(tmp_path, self._CATALOG_XML)
        spec = _valid_spec(
            component_id="nonexistent.desktop", catalog_paths=[catalog], out=tmp_path / "o.xml"
        )
        with pytest.raises(LookupError):
            patch_catalog(spec, loader=GzipXmlCatalogLoader())

"""Testy jednostkowe — budowa manifestu snap-store-proxy w `cli matrix`.

Manifest musi być adresowalny przez snapd (klucz = nazwa snapu) i nie może
reklamować URL-i, których `cli serve` nie oddaje.
"""

from __future__ import annotations

import argparse
from pathlib import Path  # noqa: TC003  (tmp_path w sygnaturach testów)

from cli.matrix_cmd import _build_snap_manifest, _make_store_proxy_provider, media_urls_for
from domains.matrix.drivers.ubuntu import UbuntuDriver
from domains.matrix.models import DistroName, DistroSpec

_BASE = "http://127.0.0.1:8899"


def _media(tmp_path: Path, *names: str) -> Path:
    media_dir = tmp_path / "media"
    media_dir.mkdir(parents=True, exist_ok=True)
    for name in names:
        (media_dir / name).write_bytes(b"\x89PNG\r\n\x1a\n")
    return media_dir


class TestMediaUrls:
    def test_url_has_no_screenshots_prefix(self, tmp_path: Path) -> None:
        """`cli serve --directory poc/media` serwuje pliki z korzenia.

        Prefiks `/screenshots/` dawał 404 na każdym medium.
        """
        media_dir = _media(tmp_path, "org.kde.kcalc.png")
        urls = media_urls_for("org.kde.kcalc", _BASE, media_dir)  # type: ignore[arg-type]
        assert urls == [f"{_BASE}/org.kde.kcalc.png"]
        assert "/screenshots/" not in urls[0]

    def test_includes_numbered_variants(self, tmp_path: Path) -> None:
        media_dir = _media(tmp_path, "org.kde.kcalc.png", "org.kde.kcalc-2.png")
        urls = media_urls_for("org.kde.kcalc", _BASE, media_dir)  # type: ignore[arg-type]
        assert urls == [
            f"{_BASE}/org.kde.kcalc.png",
            f"{_BASE}/org.kde.kcalc-2.png",
        ]

    def test_missing_files_produce_no_urls(self, tmp_path: Path) -> None:
        """Nie reklamujemy URL-a, pod którym nic nie leży."""
        media_dir = _media(tmp_path)
        assert media_urls_for("org.kde.kcalc", _BASE, media_dir) == []  # type: ignore[arg-type]

    def test_trailing_slash_in_base_is_normalised(self, tmp_path: Path) -> None:
        media_dir = _media(tmp_path, "org.gimp.GIMP.png")
        urls = media_urls_for("org.gimp.GIMP", f"{_BASE}/", media_dir)  # type: ignore[arg-type]
        assert urls == [f"{_BASE}/org.gimp.GIMP.png"]


class TestBuildSnapManifest:
    def test_keyed_by_real_snap_name(self, tmp_path: Path) -> None:
        """Klucz to nazwa snapu z SNAP_NAME_MAP, nie hash AppId.

        snapd pyta `/v2/snaps/info/<name>`; wpis pod `snap_<sha256>` byłby
        nieosiągalny.
        """
        media_dir = _media(tmp_path, "org.kde.kcalc.png", "org.gimp.GIMP.png")
        manifest = _build_snap_manifest(
            ["org.kde.kcalc", "org.gimp.GIMP"],  # type: ignore[arg-type]
            _BASE,
            media_dir,
        )
        assert set(manifest) == {"kcalc", "gimp"}
        assert manifest["kcalc"].name == "kcalc"
        assert all(not key.startswith("snap_") for key in manifest)

    def test_snap_names_come_from_driver_map(self, tmp_path: Path) -> None:
        media_dir = _media(tmp_path, "com.transmissionbt.Transmission.png")
        manifest = _build_snap_manifest(
            ["com.transmissionbt.Transmission"],  # type: ignore[arg-type]
            _BASE,
            media_dir,
        )
        expected = UbuntuDriver.SNAP_NAME_MAP["com.transmissionbt.Transmission"]
        assert set(manifest) == {expected}

    def test_app_without_mapping_is_skipped(self, tmp_path: Path) -> None:
        """Driver nie umie otworzyć takiej appki — wpis byłby martwy."""
        media_dir = _media(tmp_path, "org.example.NoSuchApp.png", "org.kde.kcalc.png")
        manifest = _build_snap_manifest(
            ["org.example.NoSuchApp", "org.kde.kcalc"],  # type: ignore[arg-type]
            _BASE,
            media_dir,
        )
        assert set(manifest) == {"kcalc"}

    def test_media_urls_point_at_serve_root(self, tmp_path: Path) -> None:
        media_dir = _media(tmp_path, "org.kde.kcalc.png", "org.kde.kcalc-2.png")
        manifest = _build_snap_manifest(
            ["org.kde.kcalc"],  # type: ignore[arg-type]
            _BASE,
            media_dir,
        )
        urls = [m.url for m in manifest["kcalc"].media]
        assert urls == [f"{_BASE}/org.kde.kcalc.png", f"{_BASE}/org.kde.kcalc-2.png"]

    def test_title_keeps_appstream_id(self, tmp_path: Path) -> None:
        media_dir = _media(tmp_path, "org.kde.kcalc.png")
        manifest = _build_snap_manifest(["org.kde.kcalc"], _BASE, media_dir)  # type: ignore[arg-type]
        assert manifest["kcalc"].title == "org.kde.kcalc"


class TestProviderWiring:
    def _args(self, media_dir: Path) -> argparse.Namespace:
        return argparse.Namespace(
            store_proxy_port=8901,
            cli_serve_base=_BASE,
            media_dir=str(media_dir),
        )

    def test_provider_builds_manifest_from_media_dir(self, tmp_path: Path) -> None:
        media_dir = _media(tmp_path, "org.kde.kcalc.png")
        provider = _make_store_proxy_provider(self._args(media_dir))
        assert provider is not None
        distro = DistroSpec(
            name=DistroName.UBUNTU,
            golden_image=tmp_path / "g.qcow2",
            store_proxy="snap-store",
        )
        proxy = provider(distro, ["org.kde.kcalc"])  # type: ignore[arg-type]
        assert proxy is not None
        assert proxy.url == "http://127.0.0.1:8901"

    def test_provider_returns_none_without_store_proxy(self, tmp_path: Path) -> None:
        media_dir = _media(tmp_path, "org.kde.kcalc.png")
        provider = _make_store_proxy_provider(self._args(media_dir))
        assert provider is not None
        distro = DistroSpec(name=DistroName.FEDORA_KDE, golden_image=tmp_path / "g.qcow2")
        assert provider(distro, ["org.kde.kcalc"]) is None  # type: ignore[arg-type]


__all__: list[str] = []

"""Testy importera katalogów zebranych z gości (domains.corpus.guest)."""

from __future__ import annotations

import gzip
import json
import tarfile
from pathlib import Path

from domains.corpus.guest import GUEST_SOURCES, classify, discover, import_guest
from domains.corpus.index import IndexWriter

_FIX = Path(__file__).resolve().parent.parent / "fixtures" / "corpus"


def _build_guest_dir(root: Path) -> Path:
    """Odtwarza układ ścieżek, jaki `fetch` Ansible zostawia w corpus/guest/."""
    gd = root / "guest"
    # fedora: katalog dystrybucji (rpm/AppStream) + flatpak remote
    fx = gd / "fedora" / "collector-fedora" / "usr" / "share" / "swcatalog" / "xml"
    fx.mkdir(parents=True)
    xml = (_FIX / "fedora-appstream-sample.xml").read_bytes()
    with gzip.open(fx / "fedora.xml.gz", "wb") as fh:
        fh.write(xml)
    fp = (
        gd
        / "fedora"
        / "collector-fedora"
        / "var"
        / "lib"
        / "flatpak"
        / "appstream"
        / "flathub"
        / "x86_64"
        / "active"
    )
    fp.mkdir(parents=True)
    with gzip.open(fp / "appstream.xml.gz", "wb") as fh:
        fh.write(xml)
    # ubuntu: DEP-11 (apt) + snapd find tgz
    du = gd / "ubuntu" / "collector-ubuntu" / "var" / "lib" / "apt" / "lists"
    du.mkdir(parents=True)
    (du / "archive.ubuntu.com_ubuntu_dists_noble_main_dep11_Components-amd64.yml.gz").write_bytes(
        (_FIX / "ubuntu-dep11-sample.yml.gz").read_bytes()
    )
    snapdir = root / "snapbuild" / "snap-find"
    snapdir.mkdir(parents=True)
    (snapdir / "find-utilities.json").write_text(
        json.dumps(
            {
                "result": [
                    {
                        "name": "kcalc",
                        "id": "snapid123",
                        "media": [
                            {
                                "type": "screenshot",
                                "url": "https://snapcraft.example/kcalc-1.png",
                                "width": 1200,
                                "height": 800,
                            },
                            {"type": "icon", "url": "https://snapcraft.example/icon.png"},
                        ],
                    }
                ]
            }
        )
    )
    with tarfile.open(gd / "ubuntu" / "snap-find.tgz", "w:gz") as tar:
        tar.add(snapdir / "find-utilities.json", arcname="snap-find/find-utilities.json")
    return gd


class TestClassify:
    def test_flatpak_remote_from_path(self, tmp_path: Path) -> None:
        p = tmp_path / "x/var/lib/flatpak/appstream/flathub/x86_64/active/appstream.xml.gz"
        p.parent.mkdir(parents=True)
        p.touch()
        cat = classify(p)
        assert cat is not None
        assert cat.source == "guest-flatpak"
        assert cat.notes == "remote=flathub"

    def test_dep11_by_name(self, tmp_path: Path) -> None:
        p = tmp_path / "archive_dists_noble_main_dep11_Components-amd64.yml.gz"
        p.touch()
        cat = classify(p)
        assert cat is not None
        assert cat.source == "guest-dep11"

    def test_plain_appstream_xml_gz(self, tmp_path: Path) -> None:
        p = tmp_path / "usr/share/swcatalog/xml/fedora.xml.gz"
        p.parent.mkdir(parents=True)
        p.touch()
        cat = classify(p)
        assert cat is not None
        assert cat.source == "guest-appstream"

    def test_snapd_tgz_and_json(self, tmp_path: Path) -> None:
        tgz = classify(tmp_path / "snap-find.tgz")
        js = classify(tmp_path / "find-utilities.json")
        assert tgz is not None
        assert js is not None
        assert tgz.source == "guest-snapd"
        assert js.source == "guest-snapd"

    def test_unknown_is_none(self, tmp_path: Path) -> None:
        assert classify(tmp_path / "README.md") is None


class TestDiscover:
    def test_finds_all_formats(self, tmp_path: Path) -> None:
        gd = _build_guest_dir(tmp_path)
        sources_fedora = {c.source for c in discover(gd, "fedora")}
        sources_ubuntu = {c.source for c in discover(gd, "ubuntu")}
        assert sources_fedora == {"guest-appstream", "guest-flatpak"}
        assert sources_ubuntu == {"guest-dep11", "guest-snapd"}

    def test_missing_distro_is_empty(self, tmp_path: Path) -> None:
        assert discover(tmp_path / "guest", "mint") == []


class TestImportGuest:
    def test_imports_every_format(self, tmp_path: Path) -> None:
        gd = _build_guest_dir(tmp_path)
        writer = IndexWriter(tmp_path / "corpus")
        counts = import_guest(gd, writer, download_media=False)
        assert set(counts) == {
            "fedora:guest-appstream",
            "fedora:guest-flatpak",
            "ubuntu:guest-dep11",
            "ubuntu:guest-snapd",
        }
        assert all(v > 0 for v in counts.values())
        assert {e.source for e in writer.entries} <= set(GUEST_SOURCES)
        # snap: icon odrzucony, screenshot przyjęty z snap-id w notes
        snap = [e for e in writer.entries if e.source == "guest-snapd"]
        assert len(snap) == 1
        assert snap[0].app_id == "kcalc"
        assert snap[0].notes is not None
        assert "snapid123" in snap[0].notes

    def test_is_idempotent(self, tmp_path: Path) -> None:
        gd = _build_guest_dir(tmp_path)
        writer = IndexWriter(tmp_path / "corpus")
        import_guest(gd, writer, download_media=False)
        n = len(writer.entries)
        second = import_guest(gd, writer, download_media=False)
        assert second == {}
        assert len(IndexWriter(tmp_path / "corpus").entries) == n

    def test_app_filter(self, tmp_path: Path) -> None:
        gd = _build_guest_dir(tmp_path)
        writer = IndexWriter(tmp_path / "corpus")
        import_guest(gd, writer, distros=["ubuntu"], apps=["kcalc"], download_media=False)
        assert {e.app_id for e in writer.entries} == {"kcalc"}

    def test_dry_run_writes_nothing(self, tmp_path: Path) -> None:
        gd = _build_guest_dir(tmp_path)
        writer = IndexWriter(tmp_path / "corpus")
        counts = import_guest(gd, writer, download_media=False, dry_run=True)
        assert sum(counts.values()) > 0
        assert writer.entries == []
        assert not (tmp_path / "corpus" / "index.json").exists()

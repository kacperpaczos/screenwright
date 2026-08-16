"""Testy integracyjne — kolektory korpusu z mockowanym HTTP."""

import json
from pathlib import Path
from unittest.mock import MagicMock

from domains.corpus.sources.flathub import FlathubSource
from shared.http_client import HttpClient
from shared.media import fetch_to_corpus

FIXTURE_DIR = Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "corpus"


def _mock_client_with(payload: dict) -> HttpClient:
    client = HttpClient()
    mock_response = MagicMock()
    mock_response.json.return_value = payload
    mock_response.content = b"x"
    client.get = MagicMock(return_value=mock_response)  # type: ignore[method-assign]
    return client


_REAL_FLATHUB_PAYLOAD = json.loads((FIXTURE_DIR / "flathub_kcalc.json").read_text())
_REAL_SNAP_PAYLOAD = json.loads((FIXTURE_DIR / "snap_kcalc.json").read_text())
_REAL_DEBIAN_PAYLOAD = json.loads((FIXTURE_DIR / "debian_kcalc.json").read_text())


class TestFlathubSource:
    def test_parses_real_api_response(self) -> None:
        client = _mock_client_with(_REAL_FLATHUB_PAYLOAD)
        source = FlathubSource(client=client)
        entries = source.fetch("org.kde.kcalc")
        assert len(entries) > 0
        for entry in entries:
            assert entry["app_id"] == "org.kde.kcalc"
            assert entry["distro"] == "flathub"
            assert entry["source"] == "flathub-api"
            assert entry["width"] > 0
            assert entry["height"] > 0
            assert entry["source_url"].startswith("https://dl.flathub.org/")

    def test_classifies_source_vs_thumbnail_by_url(self) -> None:
        """_orig.png to source, *_WxH@Nx.png to thumbnail."""
        client = _mock_client_with(_REAL_FLATHUB_PAYLOAD)
        source = FlathubSource(client=client)
        entries = source.fetch("org.kde.kcalc")
        kinds = {e["kind"] for e in entries}
        assert "source" in kinds
        assert "thumbnail" in kinds
        # Każdy entry source ma URL z "_orig".
        for e in entries:
            if e["kind"] == "source":
                assert "_orig" in e["source_url"]
            else:
                assert "_orig" not in e["source_url"]

    def test_empty_screenshots(self) -> None:
        client = _mock_client_with({"id": "org.kde.kcalc", "name": "KCalc"})
        source = FlathubSource(client=client)
        assert source.fetch("org.kde.kcalc") == []

    def test_handles_http_error(self) -> None:
        client = HttpClient()
        client.get = MagicMock(side_effect=Exception("connection refused"))  # type: ignore[method-assign]
        source = FlathubSource(client=client)
        assert source.fetch("org.kde.kcalc") == []

    def test_strips_desktop_suffix_from_id(self) -> None:
        client = _mock_client_with({**_REAL_FLATHUB_PAYLOAD, "id": "org.kde.kcalc.desktop"})
        source = FlathubSource(client=client)
        entries = source.fetch("org.kde.kcalc")
        for entry in entries:
            assert entry["app_id"] == "org.kde.kcalc"


class TestSnapSource:
    def test_parses_real_api_response(self) -> None:
        from domains.corpus.sources.snap import SnapSource

        client = _mock_client_with(_REAL_SNAP_PAYLOAD)
        source = SnapSource(client=client)
        entries = source.fetch("kcalc")
        assert len(entries) >= 1
        for entry in entries:
            assert entry["app_id"] == "kcalc"
            assert entry["distro"] == "snap"
            assert entry["source"] == "snap-store"
            assert entry["kind"] == "source"
            assert entry["width"] > 0

    def test_filters_out_icons(self) -> None:
        from domains.corpus.sources.snap import SnapSource

        client = _mock_client_with(_REAL_SNAP_PAYLOAD)
        source = SnapSource(client=client)
        entries = source.fetch("kcalc")
        for entry in entries:
            assert "icon" not in entry["source_url"]


class TestDebianSource:
    def test_parses_real_api_response(self) -> None:
        from domains.corpus.sources.debian import DebianSource

        client = _mock_client_with(_REAL_DEBIAN_PAYLOAD)
        source = DebianSource(client=client)
        entries = source.fetch("kcalc")
        assert len(entries) >= 2
        kinds = {e["kind"] for e in entries}
        assert "source" in kinds
        assert "thumbnail" in kinds
        for entry in entries:
            assert entry["pkgname"] == "kcalc"

    def test_handles_missing_dimensions(self) -> None:
        from domains.corpus.sources.debian import DebianSource

        payload = {
            "package": "kcalc",
            "screenshots": [{"screenshot_image_url": "https://x/y.png"}],
        }
        client = _mock_client_with(payload)
        source = DebianSource(client=client)
        entries = source.fetch("kcalc")
        assert len(entries) == 1


class TestUbuntuDep11Source:
    def test_parses_real_yaml(self) -> None:
        from domains.corpus.sources.ubuntu_dep11 import UbuntuDep11Source

        client = HttpClient()
        sample = (FIXTURE_DIR / "ubuntu-dep11-sample.yml.gz").read_bytes()
        mock_response = MagicMock()
        mock_response.content = sample
        client.get = MagicMock(return_value=mock_response)  # type: ignore[method-assign]

        source = UbuntuDep11Source(client=client)
        entries = source.fetch("libreoffice-writer")
        assert len(entries) >= 1
        for entry in entries:
            assert entry["distro"] == "ubuntu"
            assert entry["source"] == "ubuntu-dep11"
            assert entry["width"] > 0
            assert entry["pkgname"] == "libreoffice-writer"


class TestFedoraSource:
    def test_parses_real_xml(self) -> None:
        from domains.corpus.sources.fedora import FedoraSource

        client = HttpClient()
        mock_response = MagicMock()
        mock_response.content = (FIXTURE_DIR / "fedora-appstream-sample.xml").read_bytes()
        client.get = MagicMock(return_value=mock_response)  # type: ignore[method-assign]

        source = FedoraSource(client=client)
        entries = source.fetch("libreoffice-writer.desktop")
        assert isinstance(entries, list)


class TestElementarySource:
    def test_parses_real_xml(self) -> None:
        from domains.corpus.sources.elementary import ElementarySource

        client = HttpClient()
        mock_response = MagicMock()
        with open(FIXTURE_DIR / "elementary-appstream-sample.xml.gz", "rb") as f:
            mock_response.content = f.read()
        client.get = MagicMock(return_value=mock_response)  # type: ignore[method-assign]

        source = ElementarySource(client=client)
        entries = source.fetch("com.github.akiraux.akira")
        assert len(entries) >= 1
        for entry in entries:
            assert entry["distro"] == "elementary"
            assert entry["source"] == "elementary-repo"
            assert "raw.githubusercontent.com" in entry["source_url"]


class TestMintSource:
    def test_dep11_join_resolves_pkgname(self) -> None:
        from domains.corpus.sources.mint import MintSource
        from domains.corpus.sources.ubuntu_dep11 import UbuntuDep11Source

        client = HttpClient()
        sample = (FIXTURE_DIR / "ubuntu-dep11-sample.yml").read_bytes()
        index_html = (FIXTURE_DIR / "mint-index-small.html").read_text()

        def make_response(content: bytes) -> MagicMock:
            r = MagicMock()
            r.content = content
            r.text = content.decode("utf-8")
            return r

        responses = iter(
            [
                make_response(index_html.encode("utf-8")),
                make_response(sample),
            ]
        )
        client.get = MagicMock(side_effect=lambda *a, **kw: next(responses))  # type: ignore[method-assign]

        dep11 = UbuntuDep11Source(client=client)
        source = MintSource(client=client, dep11=dep11)
        entries = source.fetch("libreoffice-writer")
        assert entries == []


class TestFetchToCorpus:
    def test_idempotent_download(self, tmp_path: Path) -> None:
        entries = [
            {
                "app_id": "org.kde.kcalc",
                "distro": "flathub",
                "source": "flathub-api",
                "source_url": "http://127.0.0.1:1/x.png",
                "kind": "source",
                "width": 800,
                "height": 600,
                "fetched": "2026-08-15T12:00:00Z",
                "sha256": "0" * 64,
                "file": "media/unfetched.png",
            }
        ]

        mock = MagicMock()
        mock.content = b"\x89PNG same bytes"
        mock_client = MagicMock()
        mock_client.get = MagicMock(return_value=mock)  # type: ignore[method-assign]

        out1 = fetch_to_corpus(entries, tmp_path, client=mock_client)
        out2 = fetch_to_corpus(entries, tmp_path, client=mock_client)

        assert out1[0]["sha256"] == out2[0]["sha256"]
        assert out1[0]["file"] == out2[0]["file"]
        files = list((tmp_path / "media" / "org.kde.kcalc" / "flathub" / "flathub-api").iterdir())
        assert len(files) == 1, f"powinien być 1 plik, jest {len(files)}: {files}"

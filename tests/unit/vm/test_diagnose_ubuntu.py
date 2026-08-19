"""Testy jednostkowe — parser diagnostyki snap-store."""

from __future__ import annotations

import io
import json
import subprocess
import sys
from pathlib import Path

import pytest
from vm.scripts import diagnose_ubuntu

ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "vm" / "scripts" / "diagnose_ubuntu.py"

SAMPLE_RAW = """===SECTION:snapd_version===
snap    2.61.2
snapd   2.61.2
series  16
ubuntu  24.04
kernel  6.8.0-31-generic
===END_SECTION===

===SECTION:snap_store_info===
name:      snap-store
summary:   Snap Store
publisher: Canonical✓
tracking:  latest/stable
refreshed: 2026-08-10T12:00:00Z
version:   0+git.2026.07.30
===END_SECTION===

===SECTION:snap_store_cache===
/home/test/.cache/snap-store/icons/snap-store.svg
/home/test/.cache/snap-store/themes/yaru/scalable/apps/snap-store.svg
===END_SECTION===

===SECTION:snapd_journal===
sie 18 ago 2026 12:34:56 host snapd[1234]: api=2.0 api=/v2/snaps/info/snap-store url=https://api.snapcraft.io/v2/snaps/info/snap-store
===END_SECTION===

===SECTION:api_probe===
ESTAB 0 0 192.168.122.45:443 3.231.0.0:443 users:(("snapd",pid=1234,fd=7))
===END_SECTION===

===SECTION:media_probe===
{"snap-id":"rJ9hD5gG8oQ4","media":[{"type":"screenshot","url":"https://api.snapcraft.io/api/v1/snaps/screenshots/rJ9hD5gG8oQ4/default.png"}]}
===END_SECTION===
"""


class TestParse:
    def test_snapd_version(self) -> None:
        from vm.scripts.diagnose_ubuntu import parse

        result = parse(SAMPLE_RAW)
        assert result["snapd_version"] == "2.61.2"

    def test_snap_store_metadata(self) -> None:
        from vm.scripts.diagnose_ubuntu import parse

        result = parse(SAMPLE_RAW)
        assert result["snap_store_channel"] == "latest/stable"
        assert result["snap_store_version"] == "0+git.2026.07.30"

    def test_api_endpoints_extracted(self) -> None:
        from vm.scripts.diagnose_ubuntu import parse

        result = parse(SAMPLE_RAW)
        assert any(
            "api.snapcraft.io/v2/snaps/info/snap-store" in e for e in result["api_endpoints"]
        )

    def test_cache_file_count(self) -> None:
        from vm.scripts.diagnose_ubuntu import parse

        result = parse(SAMPLE_RAW)
        assert result["cache_file_count"] == 2

    def test_media_probe_url(self) -> None:
        from vm.scripts.diagnose_ubuntu import parse

        result = parse(SAMPLE_RAW)
        assert any(
            "api.snapcraft.io/api/v1/snaps/screenshots" in e for e in result["media_url_hints"]
        )

    def test_raw_sections_preserved(self) -> None:
        from vm.scripts.diagnose_ubuntu import parse

        result = parse(SAMPLE_RAW)
        assert "snapd_version" in result["raw"]
        assert "snapd   2.61.2" in result["raw"]["snapd_version"]


_REAL_MEDIA_BODY = """{"channel-map":[{"channel":{"name":"stable"},
"download":{"url":"https://api.snapcraft.io/api/v1/snaps/download/abc_123.snap"}}],
"name":"gimp","snap":{"media":[
{"height":512,"type":"icon","url":"https://dashboard.snapcraft.io/site_media/appmedia/2025/10/gimp-logo.png","width":512},
{"height":1280,"type":"banner","url":"https://dashboard.snapcraft.io/site_media/appmedia/2025/10/banner.png","width":3840},
{"height":1080,"type":"screenshot","url":"https://dashboard.snapcraft.io/site_media/appmedia/2025/10/Screenshot-gimp-painting.png","width":1920},
{"height":1048,"type":"screenshot","url":"https://dashboard.snapcraft.io/site_media/appmedia/2025/10/Screenshot-gimp-photo.png","width":1920}
]},"snap-id":"xyz"}"""


class TestScreenshotUrls:
    """Media NIE leżą na api.snapcraft.io, a screenshoty trzeba odsiać od ikon.

    Sprawdzone na żywo: `snap info`/store API oddaje ikonę, baner i screenshoty
    pod tym samym prefiksem /site_media/, na hoście dashboard.snapcraft.io.
    Poprzednia wersja szukała ich wzorcem dopasowanym do api.snapcraft.io, więc
    `media_url_hints` zawierał wyłącznie linki do plików .snap.
    """

    def _parse(self, body: str) -> dict[str, object]:
        return diagnose_ubuntu.parse(f"===SECTION:media_probe===\n{body}\n===END_SECTION===\n")

    def test_extracts_only_screenshots(self) -> None:
        urls = self._parse(_REAL_MEDIA_BODY)["screenshot_urls"]
        assert isinstance(urls, list)
        assert len(urls) == 2
        assert all("Screenshot-gimp" in u for u in urls)

    def test_skips_icon_and_banner(self) -> None:
        urls = self._parse(_REAL_MEDIA_BODY)["screenshot_urls"]
        joined = " ".join(str(u) for u in urls)
        assert "gimp-logo" not in joined
        assert "banner" not in joined

    def test_does_not_report_snap_downloads_as_screenshots(self) -> None:
        """Wcześniej to właśnie linki do .snap zapychały `media_url_hints`."""
        urls = [str(u) for u in self._parse(_REAL_MEDIA_BODY)["screenshot_urls"]]  # type: ignore[union-attr]
        assert not any(u.endswith(".snap") for u in urls)
        assert not any("/snaps/download/" in u for u in urls)

    def test_capital_s_filename_is_matched_by_regex_fallback(self) -> None:
        """Ucięte ciało → spadamy na regex; nazwy plików mają wielkie S."""
        truncated = (
            '{"snap":{"media":[{"type":"screenshot","url":'
            '"https://dashboard.snapcraft.io/site_media/appmedia/2025/10/Screenshot-gimp.png"'
        )
        urls = self._parse(truncated)["screenshot_urls"]
        assert urls == [
            "https://dashboard.snapcraft.io/site_media/appmedia/2025/10/Screenshot-gimp.png"
        ]

    def test_empty_probe_gives_empty_list(self) -> None:
        assert self._parse("")["screenshot_urls"] == []


class TestCliInvocation:
    def test_main_via_stdin(self) -> None:
        proc = subprocess.run(
            [sys.executable, str(SCRIPT), "-"],
            input=SAMPLE_RAW,
            capture_output=True,
            text=True,
            check=True,
        )
        result = json.loads(proc.stdout)
        assert result["snapd_version"] == "2.61.2"


class TestMainInProcess:
    """main() wołane bezpośrednio — subprocess w teście wyżej omija pomiar pokrycia."""

    def test_reads_file_argument(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        raw_path = tmp_path / "raw.txt"
        raw_path.write_text(SAMPLE_RAW, encoding="utf-8")
        assert diagnose_ubuntu.main([str(raw_path)]) == 0
        result = json.loads(capsys.readouterr().out)
        assert result["snapd_version"] == "2.61.2"
        assert result["snap_store_channel"] == "latest/stable"

    def test_reads_stdin_dash(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        monkeypatch.setattr("sys.stdin", io.StringIO(SAMPLE_RAW))
        assert diagnose_ubuntu.main(["-"]) == 0
        assert json.loads(capsys.readouterr().out)["cache_file_count"] == 2

    @pytest.mark.parametrize("argv", [[], ["a", "b"]])
    def test_wrong_arity_returns_2(
        self, argv: list[str], capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert diagnose_ubuntu.main(argv) == 2
        assert "usage:" in capsys.readouterr().err


__all__ = []

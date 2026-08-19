"""Testy jednostkowe — snap-store-proxy (FastAPI app + start/stop)."""

from __future__ import annotations

import json
from pathlib import Path  # noqa: TC003  (Path(tmp_path / ...) w manifest fixtures)

import pytest
from domains.matrix.store_proxy import (
    SnapInfo,
    SnapMedia,
    StoreProxyConfig,
    StoreProxyServer,
    create_app,
    load_manifest_from_json,
)
from fastapi.testclient import TestClient

# Manifest jest kluczowany NAZWĄ snapu — snapd adresuje /v2/snaps/info/<name>.
_SAMPLE_MANIFEST = {
    "kcalc": SnapInfo(
        snap_id="kcalc-snap-id",
        name="kcalc",
        title="KCalc",
        description="Calculator",
        media=[
            SnapMedia(url="http://127.0.0.1:8899/org.kde.kcalc.png"),
            SnapMedia(url="http://127.0.0.1:8899/org.kde.kcalc-2.png"),
        ],
    ),
    "gimp": SnapInfo(
        snap_id="gimp-snap-id",
        name="gimp",
        title="GIMP",
        media=[SnapMedia(url="http://127.0.0.1:8899/org.gimp.GIMP.png")],
    ),
}


class TestCreateApp:
    def setup_method(self) -> None:
        self.config = StoreProxyConfig(
            manifest=_SAMPLE_MANIFEST,
            base_url="http://127.0.0.1:8899",
        )
        self.client = TestClient(create_app(self.config))

    def test_healthz(self) -> None:
        resp = self.client.get("/healthz")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["manifest_size"] == 2

    def test_root(self) -> None:
        resp = self.client.get("/")
        assert resp.status_code == 200
        data = resp.json()
        assert "kcalc" in data["manifest_snaps"]
        assert data["base_url"] == "http://127.0.0.1:8899"

    def test_info_is_addressed_by_snap_name_not_id(self) -> None:
        """snapd woła /v2/snaps/info/<name>; adresowanie po snap-id było błędem."""
        by_name = self.client.get("/v2/snaps/info/kcalc")
        assert by_name.status_code == 200
        assert by_name.json()["snap-id"] == "kcalc-snap-id"

        by_id = self.client.get("/v2/snaps/info/kcalc-snap-id")
        assert by_id.status_code == 404

    def test_info_nests_media_under_snap(self) -> None:
        """Media siedzą w `snap.media[]`, nie na najwyższym poziomie odpowiedzi."""
        data = self.client.get("/v2/snaps/info/kcalc").json()
        assert "media" not in data, "media nie należą do korzenia odpowiedzi"
        media = data["snap"]["media"]
        assert len(media) == 2
        assert all(m["type"] == "screenshot" for m in media)
        assert media[0]["url"] == "http://127.0.0.1:8899/org.kde.kcalc.png"

    def test_info_has_snapcraft_envelope(self) -> None:
        data = self.client.get("/v2/snaps/info/gimp").json()
        assert set(data) >= {"name", "snap-id", "snap", "channel-map"}
        assert data["name"] == "gimp"
        assert data["snap"]["title"] == "GIMP"

    def test_unknown_snap_returns_404(self) -> None:
        resp = self.client.get("/v2/snaps/info/unknown-snap")
        assert resp.status_code == 404

    def test_refresh_returns_media_for_installed_snap_id(self) -> None:
        """snapd dla zainstalowanych snapów woła POST /v2/snaps/refresh po snap-id."""
        resp = self.client.post(
            "/v2/snaps/refresh",
            json={
                "context": [{"instance-key": "k1", "snap-id": "kcalc-snap-id"}],
                "actions": [
                    {"action": "refresh", "instance-key": "k1", "snap-id": "kcalc-snap-id"}
                ],
            },
        )
        assert resp.status_code == 200
        (result,) = resp.json()["results"]
        assert result["result"] == "refresh"
        assert result["instance-key"] == "k1"
        assert result["name"] == "kcalc"
        assert result["snap"]["media"][0]["url"] == "http://127.0.0.1:8899/org.kde.kcalc.png"

    def test_refresh_unknown_snap_id_reports_error_entry(self) -> None:
        resp = self.client.post(
            "/v2/snaps/refresh",
            json={"actions": [{"action": "refresh", "instance-key": "k9", "snap-id": "nope"}]},
        )
        assert resp.status_code == 200
        (result,) = resp.json()["results"]
        assert result["result"] == "error"
        assert result["instance-key"] == "k9"

    def test_find_returns_matching_manifest_entries(self) -> None:
        results = self.client.get("/v2/snaps/find?q=kcalc").json()["results"]
        assert [r["name"] for r in results] == ["kcalc"]
        assert results[0]["snap"]["media"][0]["url"].endswith("/org.kde.kcalc.png")

    def test_find_without_query_returns_whole_manifest(self) -> None:
        results = self.client.get("/v2/snaps/find").json()["results"]
        assert {r["name"] for r in results} == {"kcalc", "gimp"}


class TestLoadManifest:
    def test_loads_valid_json(self, tmp_path: Path) -> None:
        manifest_path = tmp_path / "manifest.json"
        manifest_path.write_text(
            json.dumps(
                [
                    {
                        "snap_id": "kcalc-id",
                        "snap_name": "kcalc",
                        "title": "KCalc",
                        "media_urls": ["http://x/kcalc.png"],
                    },
                    {
                        "snap_id": "gimp-id",
                        "snap_name": "gimp",
                        "media_urls": [],
                    },
                ]
            ),
            encoding="utf-8",
        )
        loaded = load_manifest_from_json(manifest_path)
        # Klucz to nazwa snapu, nie snap-id — inaczej /v2/snaps/info/<name> pudłuje.
        assert set(loaded) == {"kcalc", "gimp"}
        assert loaded["kcalc"].title == "KCalc"
        assert loaded["kcalc"].snap_id == "kcalc-id"
        assert loaded["gimp"].media == []

    def test_loads_skips_invalid_entries(self, tmp_path: Path) -> None:
        manifest_path = tmp_path / "manifest.json"
        manifest_path.write_text(
            json.dumps(
                [
                    {"snap_id": "good", "snap_name": "good-snap", "media_urls": []},
                    {"no_snap_id": True},
                    "not a dict",
                ]
            ),
            encoding="utf-8",
        )
        loaded = load_manifest_from_json(manifest_path)
        assert "good-snap" in loaded
        assert len(loaded) == 1

    def test_missing_file_raises(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError):
            load_manifest_from_json(tmp_path / "absent.json")

    def test_non_list_root_raises(self, tmp_path: Path) -> None:
        p = tmp_path / "manifest.json"
        p.write_text(json.dumps({"snap_id": "x"}), encoding="utf-8")
        with pytest.raises(ValueError, match="must be a list"):
            load_manifest_from_json(p)


class TestStoreProxyServer:
    """Wymaga uvicorn + httpx. subprocess start/stop, real network."""

    def test_context_manager_serves_health(self, tmp_path: Path) -> None:
        config = StoreProxyConfig(
            manifest=_SAMPLE_MANIFEST,
            base_url="http://127.0.0.1:8899",
            host="127.0.0.1",
            port=_pick_free_port(),
        )
        log_path = tmp_path / "proxy.log"
        server = StoreProxyServer(config)
        try:
            server.start(log_path=log_path)
            assert server.wait_ready(timeout=10.0), f"proxy not ready; log: {log_path.read_text()}"
            import httpx

            resp = httpx.get(f"{server.url}/healthz", timeout=2.0)
            assert resp.status_code == 200
            snap_resp = httpx.get(f"{server.url}/v2/snaps/info/gimp", timeout=2.0)
            assert snap_resp.status_code == 200
            assert snap_resp.json()["name"] == "gimp"
        finally:
            server.stop()


class TestStoreProxyServerLifecycle:
    """Ścieżki błędów start/stop — bez odpalania realnego uvicorna."""

    def _server(self) -> StoreProxyServer:
        return StoreProxyServer(
            StoreProxyConfig(manifest=_SAMPLE_MANIFEST, base_url="http://127.0.0.1:8899", port=1)
        )

    def test_url_and_base_url(self) -> None:
        server = self._server()
        assert server.url == "http://127.0.0.1:1"
        assert server.base_url == "http://127.0.0.1:8899"

    def test_start_without_uvicorn_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            "domains.matrix.store_proxy.shutil.which",
            lambda _name: None,
        )
        with pytest.raises(RuntimeError, match="uvicorn binary not found"):
            self._server().start()

    def test_start_twice_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        server = self._server()
        _patch_fake_popen(monkeypatch, poll_result=None)
        server.start()
        try:
            with pytest.raises(RuntimeError, match="already running"):
                server.start()
        finally:
            server.stop()

    def test_stop_without_start_is_noop(self) -> None:
        self._server().stop()  # nie może rzucić

    def test_wait_ready_false_when_process_dies(self, monkeypatch: pytest.MonkeyPatch) -> None:
        server = self._server()
        _patch_fake_popen(monkeypatch, poll_result=1)
        server.start()
        try:
            assert server.wait_ready(timeout=2.0) is False
        finally:
            server.stop()

    def test_context_manager_raises_when_never_ready(self, monkeypatch: pytest.MonkeyPatch) -> None:
        server = self._server()
        _patch_fake_popen(monkeypatch, poll_result=1)
        monkeypatch.setattr(server, "wait_ready", lambda timeout=10.0: False)
        with pytest.raises(RuntimeError, match="did not become ready"), server:
            pass

    def test_start_writes_log_file(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        server = self._server()
        _patch_fake_popen(monkeypatch, poll_result=None)
        log_path = tmp_path / "logs" / "proxy.log"
        server.start(log_path=log_path)
        server.stop()
        assert log_path.exists()


class _FakeProcess:
    def __init__(self, poll_result: int | None) -> None:
        self._poll_result = poll_result
        self.signals: list[int] = []

    def poll(self) -> int | None:
        return self._poll_result

    def send_signal(self, sig: int) -> None:
        self.signals.append(sig)

    def wait(self, timeout: float | None = None) -> int:
        return 0

    def kill(self) -> None:
        self._poll_result = -9


def _patch_fake_popen(monkeypatch: pytest.MonkeyPatch, *, poll_result: int | None) -> None:
    """Podmienia Popen i which — testujemy logikę cyklu życia, nie uvicorna."""
    monkeypatch.setattr(
        "domains.matrix.store_proxy.shutil.which",
        lambda _name: "/usr/bin/uvicorn",
    )
    monkeypatch.setattr(
        "domains.matrix.store_proxy.subprocess.Popen",
        lambda *args, **kwargs: _FakeProcess(poll_result),
    )


def _pick_free_port() -> int:
    import socket

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


__all__ = []

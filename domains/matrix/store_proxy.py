"""snap-store-proxy — minimalny FastAPI backend udający api.snapcraft.io.

Zwracamy JSON z naszymi URL-ami do screenshotów (``snap.media[].url``),
które wskazują na host-served ``cli serve`` (domyślnie port 8899).

Endpointy odwzorowują kształt Snap Store API v2 (nie wymyślony własny):

- ``GET  /v2/snaps/info/<snap-NAME>`` — snapd adresuje snapy **nazwą**, nie
  snap-id; odpowiedź ma ``name``/``snap-id``/``snap``/``channel-map``,
  a media siedzą w ``snap.media`` (nie na najwyższym poziomie).
- ``POST /v2/snaps/refresh`` — endpoint używany przez snapd dla już
  zainstalowanych snapów; ``actions[].snap-id`` → wynik z ``instance-key``.
- ``GET  /v2/snaps/find?q=<query>`` — wyszukiwanie po nazwie/tytule.
- ``GET  /healthz`` — health check dla ``wait_ready()``.

Manifest (które snapy + screenshoty) dostarcza wywołujący: ``create_app``
przyjmuje ``dict[snap_name, SnapInfo]`` + base_url serwera screenshotów.

.. warning::

   **Wpięcie proxy w snapd nie jest zweryfikowane na żywo.** ``proxy.store``
   nie przyjmuje URL-a — ``snap set core proxy.store=<store-id>`` bierze
   *identyfikator store'a*, a URL snapd rozwiązuje z podpisanej asercji
   ``store`` (którą trzeba wcześniej ``snap ack``). Samo wskazanie
   ``http://10.0.2.2:<port>`` nie zadziała. Ten moduł jest więc na dziś
   poprawny protokolarnie, ale nie ma ścieżki wpięcia — patrz
   ``docs/snap-store-diagnostics.md`` §"Ograniczenia".
"""

from __future__ import annotations

import json
import os
import shutil
import signal
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path  # noqa: TC003  (used in path.exists()/read_text() runtime calls)
from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from shared.logging import log_entry


class SnapMedia(BaseModel):
    """Jeden screenshot w odpowiedzi API (kształt ``snap.media[]``)."""

    model_config = ConfigDict(extra="forbid")

    type: str = "screenshot"
    url: str
    width: int | None = None
    height: int | None = None


class SnapInfo(BaseModel):
    """Manifest snapu: identyfikacja + URL-e screenshotów."""

    model_config = ConfigDict(extra="forbid")

    snap_id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    title: str = Field(min_length=1)
    media: list[SnapMedia] = Field(default_factory=list)
    description: str = ""
    summary: str = ""


@dataclass
class StoreProxyConfig:
    """Konfiguracja proxy.

    ``manifest`` jest kluczowany **nazwą snapu** — tak samo, jak snapd
    adresuje ``/v2/snaps/info/<name>``. Klucz po snap-id był błędem: snapd
    nigdy nie pyta po id w tej ścieżce.
    """

    manifest: dict[str, SnapInfo] = field(default_factory=dict)
    base_url: str = "http://127.0.0.1:8899"
    port: int = 8900
    host: str = "127.0.0.1"

    def by_snap_id(self) -> dict[str, SnapInfo]:
        """Indeks odwrotny — ``/v2/snaps/refresh`` adresuje snapy po snap-id."""
        return {info.snap_id: info for info in self.manifest.values()}


class RefreshAction(BaseModel):
    """Jedna akcja w ``POST /v2/snaps/refresh``."""

    model_config = ConfigDict(extra="allow", populate_by_name=True)

    action: str = "refresh"
    instance_key: str = Field(default="", alias="instance-key")
    snap_id: str = Field(default="", alias="snap-id")
    name: str = ""


class RefreshRequest(BaseModel):
    """Ciało ``POST /v2/snaps/refresh`` (``context`` ignorujemy)."""

    model_config = ConfigDict(extra="allow")

    actions: list[RefreshAction] = Field(default_factory=list)


def _snap_body(snap: SnapInfo) -> dict[str, Any]:
    """Obiekt ``snap`` z odpowiedzi API — tu żyją media."""
    return {
        "name": snap.name,
        "title": snap.title,
        "summary": snap.summary or snap.title,
        "description": snap.description,
        "media": [m.model_dump(exclude_none=True) for m in snap.media],
    }


def _info_payload(snap: SnapInfo) -> dict[str, Any]:
    """Odpowiedź ``GET /v2/snaps/info/<name>``."""
    return {
        "name": snap.name,
        "snap-id": snap.snap_id,
        "default-track": None,
        "snap": _snap_body(snap),
        "channel-map": [],
    }


def create_app(config: StoreProxyConfig) -> FastAPI:
    """Zwraca FastAPI app z endpointami snap-store API."""
    app = FastAPI(title="screenwright snap-store-proxy", version="0.2.0")

    @app.get("/v2/snaps/info/{snap_name}")
    def get_snap_info(snap_name: str) -> dict[str, Any]:
        snap = config.manifest.get(snap_name)
        if snap is None:
            raise HTTPException(status_code=404, detail=f"snap {snap_name!r} not in manifest")
        return _info_payload(snap)

    @app.post("/v2/snaps/refresh")
    def refresh_snaps(body: RefreshRequest) -> dict[str, Any]:
        """Metadane dla już zainstalowanych snapów — adresowane po snap-id."""
        index = config.by_snap_id()
        results: list[dict[str, Any]] = []
        for action in body.actions:
            snap = index.get(action.snap_id) or config.manifest.get(action.name)
            if snap is None:
                results.append(
                    {
                        "result": "error",
                        "instance-key": action.instance_key,
                        "snap-id": action.snap_id,
                        "error": {"code": "not-found", "message": "snap not in manifest"},
                    }
                )
                continue
            results.append(
                {
                    "result": action.action or "refresh",
                    "instance-key": action.instance_key,
                    "snap-id": snap.snap_id,
                    "name": snap.name,
                    "snap": _snap_body(snap),
                }
            )
        return {"results": results}

    @app.get("/v2/snaps/find")
    def find_snaps(q: str = "") -> dict[str, Any]:
        """Wyszukiwanie po nazwie/tytule; puste ``q`` zwraca cały manifest."""
        needle = q.strip().casefold()
        matches = [
            snap
            for snap in config.manifest.values()
            if not needle or needle in snap.name.casefold() or needle in snap.title.casefold()
        ]
        return {
            "results": [
                {"name": snap.name, "snap-id": snap.snap_id, "snap": _snap_body(snap)}
                for snap in matches
            ]
        }

    @app.get("/healthz")
    def health() -> dict[str, Any]:
        return {"status": "ok", "manifest_size": len(config.manifest)}

    @app.get("/")
    def root() -> dict[str, Any]:
        return {
            "service": "screenwright snap-store-proxy",
            "manifest_snaps": list(config.manifest),
            "base_url": config.base_url,
        }

    return app


def load_manifest_from_json(path: Path) -> dict[str, SnapInfo]:
    """Wczytuje manifest z JSON-a (lista {snap_id, snap_name, media_urls}).

    Zwracany dict jest kluczowany **nazwą snapu** — patrz ``StoreProxyConfig``.
    """
    if not path.exists():
        raise FileNotFoundError(path)
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        raise ValueError(f"manifest root must be a list, got {type(raw).__name__}")
    out: dict[str, SnapInfo] = {}
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        snap_id = entry.get("snap_id")
        name = entry.get("snap_name") or entry.get("name")
        title = entry.get("title") or name
        media_urls = entry.get("media_urls") or []
        if not snap_id or not name:
            continue
        out[name] = SnapInfo(
            snap_id=snap_id,
            name=name,
            title=title or name,
            media=[SnapMedia(url=url) for url in media_urls],
            description=entry.get("description", ""),
        )
    return out


_SUBPROCESS_SCRIPT = """
import json
import sys

sys.path.insert(0, ".")

from domains.matrix.store_proxy import SnapInfo, StoreProxyConfig, create_app
import uvicorn

cfg_dict = json.loads(sys.argv[1])
cfg_dict["manifest"] = {
    snap_name: SnapInfo(**info)
    for snap_name, info in cfg_dict.pop("manifest_items").items()
}
cfg = StoreProxyConfig(**cfg_dict)
app = create_app(cfg)
uvicorn.run(app, host=cfg.host, port=cfg.port, log_level="warning")
"""


class StoreProxyServer:
    """Start/stop uvicorn w subprocess. Wstrzymuje runner między create/destroy."""

    def __init__(self, config: StoreProxyConfig) -> None:
        self._config = config
        self._process: subprocess.Popen[bytes] | None = None
        self._log_file: object | None = None

    @property
    def url(self) -> str:
        return f"http://{self._config.host}:{self._config.port}"

    @property
    def base_url(self) -> str:
        return self._config.base_url

    def start(self, log_path: Path | None = None) -> None:
        if self._process is not None:
            raise RuntimeError("proxy already running")
        uvicorn_path = shutil.which("uvicorn")
        if uvicorn_path is None:
            raise RuntimeError("uvicorn binary not found in PATH (pip install uvicorn)")
        if log_path is not None:
            log_path.parent.mkdir(parents=True, exist_ok=True)
            log_file = log_path.open("wb")
        else:
            log_file = subprocess.DEVNULL
        payload = {
            "manifest_items": {
                snap_name: info.model_dump() for snap_name, info in self._config.manifest.items()
            },
            "base_url": self._config.base_url,
            "port": self._config.port,
            "host": self._config.host,
        }
        env = {**os.environ, "PYTHONPATH": os.getcwd()}
        log_entry(20, "store_proxy.start", port=self._config.port)
        self._process = subprocess.Popen(
            [sys.executable, "-c", _SUBPROCESS_SCRIPT, json.dumps(payload)],
            stdout=log_file,
            stderr=log_file,
            stdin=subprocess.DEVNULL,
            env=env,
        )
        self._log_file = log_file

    def wait_ready(self, timeout: float = 10.0) -> bool:
        """Czeka aż /healthz odpowie 200."""
        import httpx

        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                resp = httpx.get(f"{self.url}/healthz", timeout=1.0)
                if resp.status_code == 200:
                    return True
            except httpx.HTTPError:
                pass
            if self._process is not None and self._process.poll() is not None:
                return False
            time.sleep(0.1)
        return False

    def stop(self) -> None:
        if self._process is None:
            return
        try:
            self._process.send_signal(signal.SIGTERM)
            try:
                self._process.wait(timeout=5.0)
            except subprocess.TimeoutExpired:
                self._process.kill()
                self._process.wait(timeout=2.0)
        finally:
            self._process = None
            log_handle = self._log_file
            self._log_file = None
        if log_handle is not None and log_handle is not subprocess.DEVNULL:
            close = getattr(log_handle, "close", None)
            if callable(close):
                close()
        log_entry(20, "store_proxy.stop", port=self._config.port)

    def __enter__(self) -> StoreProxyServer:
        self.start()
        if not self.wait_ready():
            self.stop()
            raise RuntimeError("snap-store-proxy did not become ready")
        return self

    def __exit__(self, *exc: object) -> None:
        self.stop()


__all__ = [
    "RefreshAction",
    "RefreshRequest",
    "SnapInfo",
    "SnapMedia",
    "StoreProxyConfig",
    "StoreProxyServer",
    "create_app",
    "load_manifest_from_json",
]

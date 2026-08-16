"""Fake backend — in-memory implementacja LibvirtBackend do testów."""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from shared.types import Sha256

if TYPE_CHECKING:
    from pathlib import Path


@dataclass
class FakeCall:
    method: str
    args: tuple[Any, ...]
    kwargs: dict[str, Any]
    at: float


@dataclass
class DomainState:
    name: str
    xml: str
    created: bool = False
    started: bool = False
    saved: bool = False
    destroyed: bool = False


@dataclass
class OverlayState:
    golden: Path
    overlay: Path
    exists: bool = False


_DEFAULT_PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR"
    b"\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4"
    b"\x89\x00\x00\x00\rIDATx\x9cc\xfc\xff\xff?\x03\x00\x05\xfe\x02\xfe"
    b"\xa3\x35\x81\x84\x00\x00\x00\x00IEND\xaeB`\x82"
)


class FakeBackend:
    """In-memory backend symulujący virsh.

    - `calls` to lista wszystkich wywołań (asercja w testach).
    - `screenshot_bytes` to zawartość zwracana przez screenshot() (PNG 1x1).
    - `agent_output` to dict komenda -> stdout (domyślnie "").
    - `raise_on` to set nazw metod, które rzucają RuntimeError (symulacja błędu).
    - `create_overlay` tworzy pusty plik w `overlay`, żeby dalszy kod mógł
      sprawdzić cleanup tak samo jak na produkcji.
    """

    def __init__(
        self,
        *,
        screenshot_bytes: bytes | None = None,
        agent_output: dict[str, str] | None = None,
        raise_on: set[str] | None = None,
    ) -> None:
        self._screenshot_bytes = screenshot_bytes if screenshot_bytes is not None else _DEFAULT_PNG
        self._agent_output = agent_output or {}
        self._raise_on = raise_on or set()
        self._domains: dict[str, DomainState] = {}
        self._overlays: dict[Path, OverlayState] = {}
        self._states: dict[Path, str] = {}
        self.calls: list[FakeCall] = []

    def _record(self, method: str, *args: Any, **kwargs: Any) -> None:
        if method in self._raise_on:
            raise RuntimeError(f"backend error in {method}")
        self.calls.append(FakeCall(method, args, kwargs, time.time()))

    @property
    def domains(self) -> dict[str, DomainState]:
        return dict(self._domains)

    @property
    def overlays(self) -> dict[Path, OverlayState]:
        return dict(self._overlays)

    @property
    def states(self) -> dict[Path, str]:
        return dict(self._states)

    def create_overlay(self, golden: Path, overlay: Path) -> None:
        self._record("create_overlay", golden, overlay)
        overlay.parent.mkdir(parents=True, exist_ok=True)
        overlay.touch(exist_ok=True)
        self._overlays[overlay] = OverlayState(golden=golden, overlay=overlay, exists=True)

    def define(self, xml: str, name: str) -> None:
        self._record("define", xml, name)
        self._domains[name] = DomainState(name=name, xml=xml)

    def create(self, xml: str, name: str) -> None:
        self._record("create", xml, name)
        state = self._domains.setdefault(name, DomainState(name=name, xml=xml))
        state.created = True

    def start(self, name: str) -> None:
        self._record("start", name)
        state = self._domains.setdefault(name, DomainState(name=name, xml=""))
        state.started = True

    def destroy(self, name: str) -> None:
        self._record("destroy", name)
        if name in self._domains:
            self._domains[name].destroyed = True

    def save(self, name: str, state_file: Path) -> None:
        self._record("save", name, state_file)
        state_file.parent.mkdir(parents=True, exist_ok=True)
        state_file.write_text(f"saved-state-for-{name}")
        self._states[state_file] = name
        if name in self._domains:
            self._domains[name].saved = True

    def restore(self, state_file: Path) -> str:
        self._record("restore", state_file)
        if state_file not in self._states:
            raise RuntimeError(f"no fake save file at {state_file}")
        name = self._states[state_file]
        state = self._domains.setdefault(name, DomainState(name=name, xml=""))
        state.started = True
        return name

    def screenshot(self, name: str, out_path: Path) -> Path:
        self._record("screenshot", name, out_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        if not out_path.exists():
            out_path.write_bytes(self._screenshot_bytes)
        return out_path

    def domifaddr(self, name: str) -> str:
        self._record("domifaddr", name)
        return f"192.168.122.{hash(name) % 200 + 50}"

    def qemu_agent_exec(self, name: str, command: list[str], timeout: float = 30.0) -> str:
        self._record("qemu_agent_exec", name, command, timeout)
        key = " ".join(command)
        return self._agent_output.get(key, "")


def compute_screenshot_hash(payload: bytes) -> Sha256:
    import hashlib

    return Sha256(hashlib.sha256(payload).hexdigest())


def make_unique_name(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:6]}"


__all__ = ["FakeBackend", "FakeCall", "compute_screenshot_hash", "make_unique_name"]

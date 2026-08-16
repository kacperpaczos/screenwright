"""Adapter X11 — Xvfb + Xlib (bez importu Xlib w modułach typowanych)."""

from __future__ import annotations

import os
import subprocess
import time
from typing import TYPE_CHECKING

from shared.hashing import sha256_file
from shared.logging import log_entry
from shared.settings import load_settings

from domains.capture.models import MIN_H, MIN_W, WindowInfo

if TYPE_CHECKING:
    from pathlib import Path

    from shared.types import Sha256


class XvfbBackend:
    """Adapter Xvfb."""

    def __init__(self, display_num: int | None = None, screen: str | None = None) -> None:
        settings = load_settings()
        self._display_num = display_num or settings.capture_display_num
        self._screen = screen or settings.capture_screen
        self._process: subprocess.Popen[bytes] | None = None

    def start(self) -> str:
        display = f":{self._display_num}"
        self._process = subprocess.Popen(
            ["Xvfb", display, "-screen", "0", self._screen],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        time.sleep(2)
        return display

    def terminate(self) -> None:
        if self._process is None:
            return
        self._process.terminate()
        try:
            self._process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self._process.kill()
        self._process = None


class XlibWindowDiscovery:
    """Adapter wykrywania okien przez Xlib."""

    def wait_for_window(self, display: str, deadline_monotonic: float) -> WindowInfo:
        from Xlib import display as xdisplay

        d = xdisplay.Display(display)
        while time.time() < deadline_monotonic:
            try:
                root = d.screen().root
                for child in root.query_tree().children:
                    attrs = child.get_attributes()
                    if attrs.map_state != 2:
                        continue
                    geom = child.get_geometry()
                    if geom.width >= MIN_W and geom.height >= MIN_H:
                        return WindowInfo(
                            win_id=int(child.id),
                            width=int(geom.width),
                            height=int(geom.height),
                        )
            except Exception as exc:
                log_entry(20, "capture.xlib.scan_error", error=str(exc))
            time.sleep(0.25)
        raise TimeoutError("no window appeared within deadline")


class ImageMagickGrabber:
    """Adapter grab przez `import` z ImageMagick."""

    def grab(self, win_id: int, out_path: Path, display: str) -> tuple[Path, Sha256]:
        env = dict(os.environ, DISPLAY=display)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            ["import", "-window", hex(win_id), str(out_path)],
            env=env,
            check=True,
        )
        return out_path, sha256_file(out_path)


__all__ = ["ImageMagickGrabber", "XlibWindowDiscovery", "XvfbBackend"]

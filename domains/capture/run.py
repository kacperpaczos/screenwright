"""Główna funkcja domeny capture."""

from __future__ import annotations

import contextlib
import os
import signal
import subprocess
import time
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from shared.logging import log_entry

from domains.capture.models import CaptureResult, CaptureSpec
from domains.capture.x11 import ImageMagickGrabber, XlibWindowDiscovery, XvfbBackend

if TYPE_CHECKING:
    from shared.types import Sha256

    from domains.capture.ports import DisplayBackend, FrameGrabber, WindowDiscovery


def run(
    spec: CaptureSpec,
    *,
    display: DisplayBackend | None = None,
    discovery: WindowDiscovery | None = None,
    grabber: FrameGrabber | None = None,
) -> CaptureResult:
    display_backend = display or XvfbBackend()
    window_discovery = discovery or XlibWindowDiscovery()
    frame_grabber = grabber or ImageMagickGrabber()

    disp = display_backend.start()
    app: subprocess.Popen[bytes] | None = None
    try:
        env = _build_env(disp)
        app = subprocess.Popen(
            spec.cmd,
            shell=False,
            env=env,
            preexec_fn=os.setsid,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        deadline = time.time() + spec.timeout
        try:
            window = window_discovery.wait_for_window(disp, deadline)
        except TimeoutError:
            raise RuntimeError("the application mapped no window in time") from None

        started = time.time()
        settle_deadline = started + spec.settle_timeout
        prev: Sha256 | None = None
        first: Sha256 | None = None
        repeats = 0
        settled = False
        frames = 0
        while time.time() < settle_deadline:
            _, digest = frame_grabber.grab(window.win_id, spec.out, disp)
            frames += 1
            if first is None:
                first = digest
            repeats = repeats + 1 if digest == prev else 1
            prev = digest
            elapsed = time.time() - started
            if repeats >= spec.stable_frames and elapsed >= spec.min_wait:
                if spec.require_change and digest == first:
                    repeats = 0
                else:
                    settled = True
                    log_entry(
                        20,
                        "capture.settled",
                        elapsed=elapsed,
                        repeats=repeats,
                    )
                    break
            time.sleep(0.5)
        if not settled:
            log_entry(30, "capture.not_settled")
        return CaptureResult(
            out=spec.out,
            window=window,
            settled=settled,
            elapsed=time.time() - started,
            frames_captured=frames,
        )
    finally:
        if app is not None:
            with contextlib.suppress(Exception):
                os.killpg(os.getpgid(app.pid), signal.SIGTERM)
            time.sleep(0.5)
        display_backend.terminate()


def _build_env(disp: str) -> dict[str, str]:
    env = dict(os.environ)
    env.pop("WAYLAND_DISPLAY", None)
    env.update(
        DISPLAY=disp,
        LC_ALL="C",
        XDG_DATA_HOME=os.path.expanduser("~/.local/share"),
        GDK_BACKEND="x11",
        GSK_RENDERER="cairo",
        QT_QPA_PLATFORM="xcb",
        QT_QUICK_BACKEND="software",
    )
    return env


__all__ = ["run"]


def _typecheck_only() -> None:
    datetime.now(UTC)

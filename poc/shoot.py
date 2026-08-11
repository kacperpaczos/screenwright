#!/usr/bin/env python3
"""
Deterministic screenshot of an application window under Xvfb.

Rather than guessing a screen size and sleeping for a fixed time, this:
  * waits for the application to map a top-level window (via Xlib),
  * crops to that window's real geometry, so screen size stops mattering,
  * waits for the image to stop changing, which replaces guessing at
    "how many seconds does this application need".

Frame stability alone is not enough: an application showing a loading screen is
stable too. So stability only counts after --min-wait, requires --stable-frames
identical frames in a row, and --require-change rejects a frame identical to the
first one observed, which means nothing was drawn at all.

Usage:
    shoot.py --cmd /usr/bin/kcalc --out kcalc.png
"""

import argparse
import hashlib
import os
import signal
import subprocess
import sys
import time

DISPLAY_NUM = 96
SCREEN = "1600x1200x24"

# Windows smaller than this are almost always auxiliary: tooltips, transient menus.
MIN_W, MIN_H = 120, 120


def wait_for_window(display, deadline):
    """Return (id, width, height) of the first genuine top-level window."""
    from Xlib import X  # noqa: F401

    while time.time() < deadline:
        try:
            root = display.screen().root
            for child in root.query_tree().children:
                attrs = child.get_attributes()
                if attrs.map_state != 2:  # IsViewable
                    continue
                geom = child.get_geometry()
                if geom.width >= MIN_W and geom.height >= MIN_H:
                    return child.id, geom.width, geom.height
        except Exception:
            pass
        time.sleep(0.25)
    return None, 0, 0


def grab(win_id, path, disp):
    env = dict(os.environ, DISPLAY=disp)
    subprocess.run(["import", "-window", hex(win_id), path], env=env, check=True)
    return hashlib.sha256(open(path, "rb").read()).hexdigest()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cmd", required=True, help="command that starts the application")
    ap.add_argument("--out", required=True)
    ap.add_argument("--timeout", type=float, default=40.0,
                    help="how long to wait for a window to appear")
    ap.add_argument("--settle-timeout", type=float, default=20.0,
                    help="how long to wait for the window to stop changing")
    ap.add_argument("--min-wait", type=float, default=0.0,
                    help="do not accept any frame as final before this many seconds")
    ap.add_argument("--stable-frames", type=int, default=2,
                    help="how many identical frames in a row mean drawing has finished")
    ap.add_argument("--require-change", action="store_true",
                    help="reject a frame identical to the first one, meaning nothing was drawn")
    args = ap.parse_args()

    disp = f":{DISPLAY_NUM}"
    xvfb = subprocess.Popen(
        ["Xvfb", disp, "-screen", "0", SCREEN],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    time.sleep(2)

    # A clean, repeatable environment: fixed locale, software rendering, sane XDG.
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

    app = subprocess.Popen(
        args.cmd, shell=True, env=env, preexec_fn=os.setsid,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )

    rc = 1
    try:
        from Xlib import display as xdisplay
        d = xdisplay.Display(disp)

        win_id, w, h = wait_for_window(d, time.time() + args.timeout)
        if not win_id:
            print("ERROR: the application mapped no window in time", file=sys.stderr)
            return 2
        print(f"window {hex(win_id)} {w}x{h}")

        # Wait for the image to settle.
        started = time.time()
        deadline = started + args.settle_timeout
        prev, first, repeats, settled = None, None, 0, False
        while time.time() < deadline:
            digest = grab(win_id, args.out, disp)
            if first is None:
                first = digest
            repeats = repeats + 1 if digest == prev else 1
            prev = digest

            elapsed = time.time() - started
            if repeats >= args.stable_frames and elapsed >= args.min_wait:
                if args.require_change and digest == first:
                    print("frame unchanged since start, still waiting", file=sys.stderr)
                else:
                    settled = True
                    print(f"settled after {elapsed:.1f}s "
                          f"({repeats} identical frames)")
                    break
            time.sleep(0.5)

        if not settled:
            print("WARNING: image never settled, saving the last frame", file=sys.stderr)
        print(f"wrote {args.out}")
        rc = 0
    finally:
        try:
            os.killpg(os.getpgid(app.pid), signal.SIGTERM)
        except Exception:
            pass
        time.sleep(0.5)
        xvfb.terminate()
    return rc


if __name__ == "__main__":
    sys.exit(main())

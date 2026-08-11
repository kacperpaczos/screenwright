# Headless capture

`poc/shoot.py` starts an application on a private Xvfb display and saves a
screenshot of its window.

    shoot.py --cmd /usr/bin/kcalc --out kcalc.png

## Design

Two decisions make the output reproducible rather than approximately right.

**Window geometry is discovered, not assumed.** The script walks the X root
window's children through Xlib, skips anything not viewable or smaller than
120x120 (tooltips and transient menus), and crops to the real geometry of the
first genuine top-level window. Screen size therefore stops mattering; an
earlier version guessed a 520x400 display and silently clipped a 640x480 window.

**Readiness is observed, not timed.** Rather than sleeping for a fixed number of
seconds, the script grabs frames repeatedly and compares SHA-256 digests, so a
slow application is waited out and a fast one is not.

The environment is pinned for repeatability: `LC_ALL=C`, `GDK_BACKEND=x11`,
`QT_QPA_PLATFORM=xcb`, software rendering for both toolkits, `WAYLAND_DISPLAY`
removed, and `XDG_DATA_HOME` reset to a sane value.

## Frame stability is not enough

The first readiness rule was "two identical frames in a row". It fails: a
loading screen is stable too. Capturing Discover produced a clean, perfectly
stable screenshot of the word "Loading…".

Three options exist to tighten the rule:

- `--min-wait` — do not accept any frame as final before this many seconds have
  passed.
- `--stable-frames` — how many consecutive identical frames count as finished
  drawing. Two is often too few.
- `--require-change` — reject a frame identical to the very first one observed,
  which catches the case where the application drew nothing at all.

These are enough to get a correct capture of Discover's application page. Note
that Discover never reaches full stability even in 200 seconds, because a
package-size indicator keeps animating in the background; the run ends on the
timeout and saves the last frame, which is correct. For the intended workload —
capturing applications, not stores — this is not a problem, but it does show
that pixel stability alone cannot be the only readiness signal.

## Thumbnails

A store expects thumbnails alongside the source image. Fedora's
`appstream-generator` produces four sizes: 752x423, 624x351, 224x126 and 112x63.
A 4:3 application window letterboxes into these 16:9 frames, which is visible in
the result and is what the distribution's own images look like too.

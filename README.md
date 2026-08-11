# screenwright

screenwright runs an application on a headless display, captures a screenshot of
its window, and substitutes that image into the metadata a software centre reads.
It exists because store listings routinely carry screenshots that are years out
of date, and nobody refreshes them, because refreshing them is manual work.

The project was previously called `mint-screenshots`. It was renamed once Linux
Mint turned out to be one of several consumers rather than the subject.

## The problem

Getting a screenshot is the easy half. The hard half is putting it somewhere a
user will actually see it, and that depends entirely on which regime the store
belongs to:

- **Metainfo-driven** — Fedora, Flathub, Mint's flatpak path. The upstream
  project declares the image in its `metainfo.xml`; the distribution only
  re-hosts thumbnails. Fixing a stale screenshot means a pull request per
  project.
- **Community-uploaded** — Mint's deb path (community.linuxmint.com) and
  screenshots.debian.net. Anyone can upload. This is where an automated
  pipeline can deliver directly.

See [docs/where-screenshots-come-from.md](docs/where-screenshots-come-from.md)
for how this was established.

## What it does today

Two pieces, usable independently:

- `poc/shoot.py` captures an application window under Xvfb, deterministically:
  it discovers the real window geometry rather than guessing a screen size, and
  waits for the frame to stop changing rather than sleeping for a fixed number
  of seconds.
- `poc/make-override.py` builds an AppStream catalogue file that replaces a
  component's screenshots with images of your choosing, so you can see the
  result in a real software centre before publishing anything externally.

## Status

Verified end to end on Fedora 44 KDE (AppStream 1.1.3, Discover 6.7.3): a KCalc
screenshot generated under Xvfb appears in Discover in place of the upstream one
from cdn.kde.org, with no rebuild of Discover required. Details and evidence in
[docs/verification.md](docs/verification.md).

Not done: publishing to real consumers (community.linuxmint.com,
screenshots.debian.net), handling more than one application per run, and any
quality control over the captured image.

## Requirements

- Xvfb and ImageMagick (`import`) for capture
- `python3-xlib` for window discovery
- AppStream tooling (`appstreamcli`) for the substitution path
- Python 3 with GObject introspection if you want to run the isolation harness
  described in the AppStream document

## Installation

There is nothing to install. The scripts run from the checkout:

    git clone <repository> screenwright
    cd screenwright
    ./poc/shoot.py --help

The substitution path writes one file into a system directory, which is the only
step that needs root. It is a single file and it is removed again by deleting it.

## Quick start

Capture an application, then serve the images locally:

    poc/shoot.py --cmd /usr/bin/kcalc --out poc/media/kcalc-source.png
    # also produce Fedora's thumbnail sizes: 752x423, 624x351, 224x126, 112x63
    poc/serve.sh start

Build the override and install it:

    poc/make-override.py --id org.kde.kcalc.desktop \
        --base-url http://127.0.0.1:8899 --prefix kcalc \
        --out poc/90-screenwright.xml
    sudo install -m644 poc/90-screenwright.xml /usr/share/swcatalog/xml/
    sudo appstreamcli refresh --force

Confirm the substitution reached the cache before opening a store:

    appstreamcli dump org.kde.kcalc.desktop

Discover reads the AppStream pool at startup, so restart it to see the change.

## Removing the override

    sudo rm /usr/share/swcatalog/xml/90-screenwright.xml
    sudo appstreamcli refresh --force
    poc/serve.sh stop

## Repository layout

    docs/                  findings and design notes
    poc/shoot.py           headless capture
    poc/make-override.py   AppStream catalogue override generator
    poc/serve.sh           local image server (start|stop|status)
    poc/media/             generated screenshots and thumbnails
    mintinstall/           submodule: Mint Software Manager (deb-path screenshot research)
    gnome-software/        submodule: GNOME Software (screenshot fetch/display reference)
    discover/              submodule: KDE Discover (screenshot fetch/display reference)

## Documentation

- [Where software centres get their screenshots](docs/where-screenshots-come-from.md)
  — Mint's two code paths, Fedora's catalogue format, and the two regimes.
- [Overriding screenshots in AppStream](docs/appstream-overrides.md) — why
  `merge="replace"` does not work for screenshots, what does, and how to test it.
- [Headless capture](docs/capture.md) — the capture harness and why frame
  stability alone is not a readiness signal.
- [Verification log](docs/verification.md) — the end-to-end result, with
  environment notes.

## Two things that are easy to get wrong

`merge="replace"` in an AppStream catalogue **does not replace screenshots**. In
AppStream 1.1.3 the merge path copies only `name`, `summary`, `description`,
`pkgnames`, `bundles`, `icons` and `provided`. The cache rebuilds without a
single warning and nothing changes. Publish a whole component instead, with a
`priority` higher than the distribution catalogue's.

Pixel stability is a weak signal that an application has finished drawing — a
loading screen is stable too. Hence `--min-wait`, `--stable-frames` and
`--require-change` in `shoot.py`.

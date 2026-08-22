# screenwright

screenwright runs an application on a headless display, captures a screenshot of
its window, and substitutes that image into the metadata a software centre reads.

It also builds a **corpus** of screenshots used by various Linux distributions
(Fedora, Ubuntu, Mint, elementary, Flathub, Snap, Debian) and an **automated VM
matrix** that verifies those screenshots appear correctly in real software centres.

## Status

Implemented:

- `domains/capture/` — headless screenshot capture (replaces `poc/shoot.py`)
- `domains/override/` — AppStream catalogue override (replaces `poc/make-override.py`)
- `domains/corpus/` — collectors for Fedora, Flathub, Ubuntu DEP-11, Snap,
  Debian, Mint, elementary OS
- `domains/matrix/` — VM matrix orchestration with FakeBackend, drivers,
  distro_builders
- `domains/verification/` — template match verification
- `cli/` — unified CLI: `python -m cli {capture,override,collect,matrix,serve}`
- `shared/` — types, ports, http_client, hashing, results

Live status (2026-08-22): the matrix runs end to end on real libvirt clones
(`--execute --backend virsh`) — guest readiness over the agent and SSH, store
commands in the user's graphical session, change-aware screenshots, per-phase
timings and a `virsh save`/`restore` warm cache; see `docs/matrix-timing.md`.

Not implemented:

- e2e tests against actual VMs in CI (live runs are manual, rootless, on the
  developer's machine).
- Public website (TODO §8) and GUI (TODO §4).

## Architecture

```
domains/      — 5 bounded contexts (corpus, capture, override, matrix, verification)
shared/       — shared kernel: types, ports, http, hashing, results, settings
cli/          — argparse adapters that map to domain models
tests/        — unit + integration + architecture tests
schemas/      — JSON Schema files (corpus-index, ubuntu-autoinstall)
```

**Rules** (enforced by `import-linter` + `tests/architecture/test_boundaries.py`):

- `domains/*` import only from `shared/`.
- `shared/` never imports from `domains/`.
- `cli/` is the only place allowed to import multiple domains.

## Requirements

- Python ≥ 3.11
- For capture: `Xvfb`, ImageMagick (`import`), `python3-xlib`
- For corpus: outbound HTTPS to Fedora/Flathub/Ubuntu/Snap/Debian/Mint/elementary
- For matrix: libvirt/QEMU on the host (only when running outside `dry_run`)

## Install

    pip install -e ".[dev]"

## Quick start

### Capture a screenshot

    python -m cli capture --cmd kcalc --out kcalc.png

### Override an AppStream catalogue entry

    python -m cli override --id org.kde.kcalc.desktop \
        --base-url http://127.0.0.1:8899 --prefix kcalc \
        --out 90-screenwright.xml

### Serve override images locally

    python -m cli serve start --directory poc/media
    python -m cli serve stop
    python -m cli serve status

### Collect corpus from all sources

    python -m cli collect --apps apps.json --distros fedora,flathub,ubuntu,snap,debian,mint,elementary

### Plan or execute a VM matrix run

    python -m cli matrix --spec matrix-spec.json                    # plan (always safe)
    python -m cli matrix --spec matrix-spec.json --execute \
        --backend virsh --output vm/reports/matrix.json             # real libvirt run
    python -m cli matrix --spec matrix-spec.json --execute \
        --backend fake --output vm/reports/matrix.json              # dry-run with FakeBackend

`dry_run` is resolved from two places: without `--execute` the run is always a
plan; with `--execute` the spec decides — `"dry_run": true` in the JSON is a
lock that the flag does not override (the command exits with 2 and says so),
`false` or an absent key lets the run go ahead.

`--backend fake` is for tests and CI: it does NOT start real VMs and the
verification matcher compares a screenshot to itself (always score 1.0),
so any "passed" results are illustrative only. `--backend virsh` actually
calls `virsh` and requires `libvirtd` on the host.

## Testing

    make lint     # ruff + mypy
    make test     # pytest -m "not slow"
    make validate # xmllint + import-linter

## Pilot app set (`apps.json`)

10 apps that exist across all four ecosystems:

- `org.kde.kcalc` (POC app)
- `org.gimp.GIMP`
- `org.inkscape.Inkscape`
- `org.videolan.VLC`
- `org.audacityteam.Audacity`
- `org.blender.Blender`
- `org.gnome.gedit`
- `org.kde.okular`
- `org.libreoffice.LibreOffice`
- `com.transmissionbt.Transmission`

## Documentation

- `docs/platform-notes.md` — hard-won host/VM/store facts (gotchas reference)
- `docs/where-screenshots-come-from.md` — sources of screenshots in stores
- `docs/appstream-overrides.md` — why `merge="replace"` doesn't work
- `docs/override-deploy.md` — cel 2: replacing store screenshots end-to-end
- `docs/capture.md` — headless capture design
- `docs/verification.md` — end-to-end verification log
- `docs/architecture.md` — bounded contexts, dependency rules

## Layout

    domains/           # 5 bounded contexts
      corpus/          # screenshot corpus (collectors, index, ID normalization)
      capture/         # headless capture (Xvfb, Xlib, ImageMagick)
      override/        # AppStream catalogue override
      matrix/          # VM matrix orchestration (drivers, builders, runner)
      verification/    # template match verification
    shared/            # types, ports, http, hashing, results, settings
    cli/               # argparse adapters
    tests/             # unit + integration + architecture
    schemas/           # JSON Schema
    apps.json          # pilot app set (10 apps)
    matrix-spec.json   # sample matrix spec
# screenwright

screenwright runs an application on a headless display, captures a screenshot of
its window, and substitutes that image into the metadata a software centre reads.

It also builds a **corpus** of the screenshots various Linux distributions ship
(Fedora, Ubuntu, Mint, elementary, Flathub, Snap, Debian), collected from inside
real systems, and **verifies** that a substituted screenshot renders correctly in
a real software centre (proven live on GNOME Software 50 — see
`docs/override-deploy.md`).

## Status

Implemented:

- `domains/capture/` — headless screenshot capture (replaces `poc/shoot.py`)
- `domains/override/` — AppStream catalogue override (replaces `poc/make-override.py`)
- `domains/corpus/` — collectors for Fedora, Flathub, Ubuntu DEP-11, Snap,
  Debian, Mint, elementary OS
- `domains/matrix/` — VM primitives (virsh/ssh backends, guest-readiness waits)
  and golden-image builders (`distro_builders`). The run-flow engine
  (runner/warm-cache/drivers/store-proxy) was retired 2026-08-22 in favour of the
  Ansible collectors + override stack (`BACKLOG.md`, `docs/matrix-timing.md` keeps
  the Etap-0 measurements).
- `domains/verification/` — template match verification
- `cli/` — unified CLI: `python -m cli {capture,override,collect,serve,vm}`
- `shared/` — types, ports, http_client, hashing, results

Live status (2026-08-22): both product goals work end to end on real rootless
libvirt VMs. Cel 1 — 62,868 screenshots / 6,186 apps collected from inside Fedora
and Ubuntu via Ansible (`docs/collectors.md`). Cel 2 — an AppStream override
patched into the base catalogue makes GNOME Software render our screenshot
(`docs/override-deploy.md`, `docs/platform-notes.md`).

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
- For VM work (golden builds, live verification): rootless libvirt/QEMU + passt
  on the host; provisioning via Ansible (`ansible/`)

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

### Refresh the whole corpus with one command

    make refresh                        # provision collectors → collect → import → hydrate media
    # or, with knobs:
    DISTROS=fedora,ubuntu HYDRATE=20000 scripts/refresh-screenshot-db.sh
    SKIP_PROVISION=1 HYDRATE=0 scripts/refresh-screenshot-db.sh   # reuse collectors, index only

### Collect from inside real distros, and substitute a screenshot (Ansible)

    cd ansible && ansible-playbook playbooks/site.yml               # provision → collect (cel 1)
    ansible-playbook playbooks/deploy-override.yml \                # substitute + verify (cel 2)
        -e override_component_id=GameConqueror.desktop -e override_prefix=gimp

### Build golden VM images declaratively (Packer)

    packer plugins install github.com/hashicorp/qemu   # once
    packer/build-all.sh                                # ubuntu + fedora ws/kde, one VM at a time

### Patch a screenshot into an AppStream catalogue in place

    python -m cli override --patch --id GameConqueror.desktop \
        --base-url http://127.0.0.1:8080 --prefix gimp \
        --catalog /usr/share/swcatalog/xml/fedora.xml.gz \
        --out /usr/share/swcatalog/xml/fedora.xml.gz

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
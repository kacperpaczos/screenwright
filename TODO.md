# TODO

High-level product goals beyond the current capture / AppStream override POC.

## 1. Collect screenshots from major distros

Plan: [docs/plans/1-screenshot-corpus.md](docs/plans/1-screenshot-corpus.md)

Pull (or scrape / catalogue) the **current store screenshots** for the same applications from:

- [ ] **Fedora** (GNOME Software / AppStream catalogues)
- [ ] **Ubuntu** (Snap Store / AppStream / software centre paths as applicable)
- [ ] **Linux Mint** (deb community uploads + flatpak/AppStream paths)
- [ ] **elementary OS** (AppCenter)

Deliverable: a local corpus keyed by app id (e.g. AppStream `component-id` / package name) with provenance (distro, source URL, fetch date).

## 2. Match and compare corresponding screenshots

- [ ] Build a **cross-distro mapping**: same app → one row of screenshots from each distro
- [ ] Produce a **comparison set** (side-by-side or grid) so stale vs current captures are obvious
- [ ] Include **our** headless captures (`poc/shoot.py` pipeline) in the same rows for direct contrast

Deliverable: a structured comparison dataset (not just ad-hoc folders).

## 3. Research: how software centres present screenshots

Document and **compare** presentation behaviour across installers / stores (not only where images come from, but how they are shown in the UI):

- [ ] **Linux Mint** (`mintinstall` — deb path vs flatpak path)
- [ ] **GNOME Software** (`gnome-software`)
- [ ] **KDE Discover** (`discover`)
- [ ] **elementary OS AppCenter**
- [ ] Others as needed (e.g. Snap Store client, Plasma Discover backends, Flathub-facing clients)

For each, capture at least:

- layout (carousel, grid, hero image, thumbnails)
- image sizes / aspect ratios expected or enforced
- source priority (metainfo vs community upload vs CDN cache)
- failure modes (missing image, stale cache, override/merge behaviour)

Deliverable: `docs/` comparison notes (tables + screenshots of the stores themselves). Use submodules as code reference.

## 4. GUI for browsing and comparison

- [ ] Ship a **desktop or local GUI** to browse the corpus, filter by app/distro, and inspect side-by-side screenshots
- [ ] Support basic review actions (mark stale, mark good, export override / upload candidate)

## 5. UX research (how the product UI should look)

Study how large software stores present screenshots and app media, and extract patterns we should follow:

- [ ] **Apple** (App Store product pages, media gallery)
- [ ] **Google** (Play Store / related store UI)
- [ ] **Microsoft** (Microsoft Store)

Deliverable: short design notes (layout, hierarchy, image sizes, carousel vs grid, trust/freshness cues) under `docs/` before building the public site.

## 6. Automated VM matrix to test our screenshots

Plan: [docs/plans/6-vm-matrix.md](docs/plans/6-vm-matrix.md)

Build an **automatic virtual-machine method** to install/apply our screenshots and verify they appear correctly in the real software centre UI:

- [x] **Fedora Workstation** (GNOME Software 50.0) — built, booted, store opened
- [x] **Fedora KDE** (Discover 6.6.4) — built, booted, store opened
- [x] **Ubuntu 24.04** (snap-store 1390 **and** GNOME Software 46.0) — built, booted
- [ ] **Linux Mint** (mintinstall)
- [ ] **elementary OS** (AppCenter)

Goals:

- reproducible images (cloud images, Boxes, libvirt, or similar)
- scripted deploy of overrides / refreshed media
- automated or semi-automated visual check that the store shows the intended shot

Deliverable: VM definitions + orchestration scripts + a short “how to run the matrix” doc.

### Where we stand (2026-08-18)

Three golden images exist and were each verified live: autologin into a
graphical session, SSH on a key, `qemu-guest-agent` responding, and the store
opened by **the command our own driver emits**, captured with
`virsh screenshot`. Evidence:
[`docs/media/store-delivery-2026-08-18/`](docs/media/store-delivery-2026-08-18/).

Everything runs **without root**: `qemu:///session`, images under
`~/.local/share/screenwright/images`, usermode networking via passt, SSH
through a per-domain forwarded port. Nothing in the pipeline needs admin
rights — `/dev/kvm` is world-accessible and libguestfs works unprivileged.

| Image | Size | Contents |
| --- | --- | --- |
| `ubuntu-24.04.qcow2` | 4.1 G | ubuntu-desktop, gnome-software, snap-store |
| `fedora-ws.qcow2` | 6.0 G | GNOME, GNOME Software |
| `fedora-kde.qcow2` | 9.1 G | Plasma, Discover |

Rebuild with (no `sudo`, ~2 h total, unattended):

```bash
vm/build/build-keypair.sh
vm/build/install-fedora.sh ws
vm/build/install-fedora.sh kde
vm/build/seed-ubuntu.sh
```

Traps found the hard way while getting there, all fixed in the installers and
covered by tests — worth knowing before touching this again:

- Cloud/server images have **no store at all**; `virsh screenshot` captures a
  login prompt. Golden images must be full desktop installs.
- Fedora 44 KDE replaced SDDM with **`plasma-login-manager`**, which reads
  `/etc/plasmalogin.conf.d/`. An autologin file in `/etc/sddm.conf.d/` is
  silently ignored, and `plasma-setup.service` grabs seat0 before autologin.
- First-run chrome covers the store on every capture: `gnome-initial-setup`
  and `update-notifier` on Ubuntu, `gnome-tour` on Fedora WS,
  `plasma-welcome` on KDE.
- Fedora's `wheel` still prompts for a password, so `sudo` over SSH without a
  TTY fails — the installers add an explicit NOPASSWD rule.
- `virt-sparsify` fails on these images (`Read-only file system`); the build
  falls back to `qemu-img convert -c`, which never mounts the guest.

### Still to do here

- [x] Run the full matrix end to end and confirm the report references real
      framebuffer PNGs, not 70-byte `FakeBackend` placeholders — done
      2026-08-22 on Fedora WS (`docs/matrix-timing.md`): 548 KB framebuffer
      PNGs, per-phase timings in the report, warm cache in place.
- [ ] **GNOME Software driver without `--quit`.** The baseline shows the store
      cold-starting (~30–45 s to a window) for *every* app because the driver
      quits it first; `--details` on the running instance only switches the
      page. Biggest remaining lever on run time.
- [ ] **Warm template with the store already running** (save after the first
      store render), so each app is a page switch, not a cold start.
- [ ] Golden-image chrome seen on 2026-08-22: GNOME Software's "Enable Third
      Party Software Repositories?" modal covers the details page
      (`org.gnome.software show-nonfree-prompt=false` in the builder), and
      GNOME stays in the Activities overview after autologin, so the store
      window shows as a workspace thumbnail — leave the overview before the
      screenshot (driver or image setting).
- [ ] `qemu-guest-agent` is SELinux-confined (`virt_qemu_ga_t`) on Fedora:
      session commands go over SSH now. If SSH is ever unavailable, the
      alternative is an SELinux boolean/policy for the agent in the golden
      image — not explored.
- [ ] `work_root` defaults to `/tmp/screenwright-matrix` (tmpfs): screenshots
      and per-run overlays land in RAM; move it under `image_root`.
- [ ] Host memory: systemd-oomd killed the whole terminal scope on 2026-08-22
      when an image build (virt-sparsify) overlapped with matrix clones. Run
      builds and matrix passes in their own `systemd-run --user --scope`, never
      concurrently with each other.
- [ ] Suppress Discover's "Update Issue" modal (it pops over the store page).
- [ ] Rebuild `fedora-kde.qcow2` cleanly — the current one is 9.1 G because a
      killed `virt-sparsify` had already zero-filled part of the free space.
- [ ] Keep builds sequential: three concurrent installs exhausted host RAM and
      the OOM killer took one down mid-compression.

### Answered: delivery follows the distro, not the store

Measured on live VMs 2026-08-18 — full write-up with URLs and probes:
[docs/store-screenshot-delivery.md](docs/store-screenshot-delivery.md).

- **Store engine is irrelevant.** Discover and GNOME Software on Fedora return
  byte-identical screenshot URLs (same md5) — both read `fedora.xml.gz`.
- **Distro decides everything.** The *same* GNOME Software on Ubuntu uses
  DEP-11 YAML, `appstream.ubuntu.com` and a different file-naming scheme.
- **Packaging format overrides both.** Snap entries bypass AppStream entirely
  (snapd → `dashboard.snapcraft.io`).

So the override must be built **per distribution**, not per store — and snap
entries stay out of reach of any AppStream override.

Caveat recorded during the measurement: `appstream.ubuntu.com` is serving an
**expired TLS certificate** (expired 2026-07-31), so on Ubuntu no AppStream
screenshot loads today. `curl -k` returns the file fine, so it is a Canonical
outage, not our bug — but it makes deb-path comparisons on Ubuntu unreliable
until it is renewed.

- [ ] **Verify an XML override lands on Ubuntu.** `GzipXmlCatalogLoader` reads
      only `*.xml.gz`, which fits Fedora. Ubuntu's source catalog is DEP-11
      YAML, but Ubuntu *does* have `/usr/share/swcatalog/xml/`, so our XML
      override plausibly wins on priority anyway. Untested.

### Runner gap: one store per distro

`_DRIVERS_BY_DISTRO` maps one driver per `DistroName`, so Ubuntu can currently
drive either snap-store or GNOME Software, not both in one run. Comparing the
two stores on the same machine needs a store dimension in `MatrixRunSpec`
(distro × store), not just distro.

### Decided: AppStream override, not snap-store-proxy

The live measurement settled this. AppStream override covers GNOME Software
**and** Discover with one mechanism, and `docs/appstream-overrides.md` already
proves it works (full component at `priority="1"`; `merge="replace"` does not
touch screenshots).

`domains/matrix/store_proxy.py` stays in the tree — it now matches the Snap
Store API v2 shape and is verified end-to-end over HTTP (fetch → replace →
re-fetch) — but it is **parked**, because there is no verified way to point
snapd at it: `proxy.store` takes a store ID resolved from a signed `store`
assertion, not a URL, and we do not have a brand account. Snap-packaged apps
therefore stay outside the override's reach until someone decides they are in
scope.

## 7. One-click refresh of the screenshot database

- [ ] Provide an **install / setup script** and a **one-click (or one-command) solution** to refresh the screenshot corpus end-to-end
- [ ] Pipeline should: collect store images → run our captures where configured → update the comparison dataset → (optionally) refresh local AppStream overrides / media used by the site
- [ ] Document prerequisites and make the happy path boring: clone → run one script → updated database

Deliverable: e.g. `scripts/refresh-screenshot-db.sh` (or equivalent) + README section.

## 8. Public website

- [ ] Build a **www** that presents:
  - our freshly captured screenshots, and
  - the current screenshots used by other distros
- [ ] Make the comparison the main story: *what the store shows today vs what the app actually looks like*
- [ ] Prefer static or simple hosting; keep image provenance and last-updated timestamps visible

---

## Suggested order

1. Corpus + mapping (Fedora, Ubuntu, Mint, elementary)
2. Software-centre presentation research (Mint, GNOME, KDE, elementary, …)
3. Comparison dataset including our captures
4. One-click / scripted refresh of the screenshot database
5. VM matrix to validate screenshots in real stores
6. UX research (Apple / Google / Microsoft)
7. GUI for local review
8. Public website

## Housekeeping

Small, unrelated to the product goals above, but worth clearing.

- [ ] **Clean the reference submodules.** `discover/` (2 files),
  `gnome-software/` (7) and `mintinstall/` (10) have dirty working trees —
  reformatted imports, not our edits. They predate the current work and are
  never staged, so nothing has leaked into a commit, but a dirty submodule
  makes `git status` noisy and hides real pointer changes. Clear with
  `git submodule foreach git checkout .`.
- [ ] **Declare `types-python-xlib` in the dev dependencies.**
  `domains/capture/x11.py` imports `Xlib`, and `pyproject.toml` lists
  `types-PyYAML` but not the Xlib stubs, so `mypy` reports
  `Library stubs not installed for "Xlib"`. CI runs `mypy` in the `lint`
  job, so this fails there even though it looks like a local-only problem.
  One line in `[project.optional-dependencies].dev`.
- Note on running `mypy` locally: two of its complaints are environment,
  not code. `types-PyYAML` is declared but may not be installed in the
  active interpreter (`pip install -e ".[dev]"` fixes it), and the numpy
  stubs shipped for Python 3.14 fail to parse (`Type statement is only
  supported in Python 3.12 and greater`). CI pins 3.12, where this does
  not occur.

## Notes

- Submodules `mintinstall/`, `gnome-software/`, and `discover/` are reference code for **how** stores fetch and display images—use them when implementing collectors, presentation research, and VM checks.
- Prefer stable app identifiers over display names when joining rows across distros.
- “One-click” can start as one well-documented command; polish into a true installer later if needed.

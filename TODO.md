# TODO

High-level product goals beyond the current capture / AppStream override POC.

## 1. Collect screenshots from major distros

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

Build an **automatic virtual-machine method** to install/apply our screenshots and verify they appear correctly in the real software centre UI:

- [ ] **Fedora** (GNOME Software)
- [ ] **Ubuntu** (default store path(s))
- [ ] **GNOME** desktop + GNOME Software (if not already covered by Fedora/Ubuntu spins)
- [ ] **KDE** (Discover)
- [ ] **Linux Mint** (mintinstall)
- [ ] **elementary OS** (AppCenter)

Goals:

- reproducible images (cloud images, Boxes, libvirt, or similar)
- scripted deploy of overrides / refreshed media
- automated or semi-automated visual check that the store shows the intended shot

Deliverable: VM definitions + orchestration scripts + a short “how to run the matrix” doc.

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

## Notes

- Submodules `mintinstall/`, `gnome-software/`, and `discover/` are reference code for **how** stores fetch and display images—use them when implementing collectors, presentation research, and VM checks.
- Prefer stable app identifiers over display names when joining rows across distros.
- “One-click” can start as one well-documented command; polish into a true installer later if needed.

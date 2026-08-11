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

## 3. GUI for browsing and comparison

- [ ] Ship a **desktop or local GUI** to browse the corpus, filter by app/distro, and inspect side-by-side screenshots
- [ ] Support basic review actions (mark stale, mark good, export override / upload candidate)

## 4. UX research (how this should look)

Study how large software stores present screenshots and app media, and extract patterns we should follow:

- [ ] **Apple** (App Store product pages, media gallery)
- [ ] **Google** (Play Store / related store UI)
- [ ] **Microsoft** (Microsoft Store)

Deliverable: short design notes (layout, hierarchy, image sizes, carousel vs grid, trust/freshness cues) under `docs/` before building the public site.

## 5. Public website

- [ ] Build a **www** that presents:
  - our freshly captured screenshots, and
  - the current screenshots used by other distros
- [ ] Make the comparison the main story: *what the store shows today vs what the app actually looks like*
- [ ] Prefer static or simple hosting; keep image provenance and last-updated timestamps visible

---

## Suggested order

1. Corpus + mapping (Fedora, Ubuntu, Mint, elementary)  
2. Comparison dataset including our captures  
3. UX research (Apple / Google / Microsoft)  
4. GUI for local review  
5. Public website  

## Notes

- Submodules `mintinstall/`, `gnome-software/`, and `discover/` are reference code for **how** stores fetch and display images—use them when implementing collectors and when documenting store behaviour.
- Prefer stable app identifiers over display names when joining rows across distros.

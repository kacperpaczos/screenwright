# Plan: screenshot corpus from major distros (TODO §1)

Build a local corpus of the **current store screenshots** for a set of
applications, across Fedora, Ubuntu, Linux Mint and elementary OS, keyed by a
stable app id and carrying provenance (distro, source URL, fetch date).

Research basis: every endpoint below was **verified alive by live fetch on
2026-08-15** unless marked otherwise.

## What each store actually reads (the sources)

| Ecosystem | Source of truth | Endpoint |
|---|---|---|
| Fedora (rpm) | `appstream-data` rpm → `fedora.xml.gz` | `https://kojipkgs.fedoraproject.org/packages/appstream-data/<ver>/<rel>/noarch/…rpm` (also on dl.fedoraproject.org mirrors) |
| Fedora thumbnails | Fedora's own screenshot cache | `http://dl.fedoraproject.org/pub/alt/screenshots/f<N>/<WxH>/<id>-<md5>.png` — sizes 112x63, 224x126, 624x351, 752x423 |
| Flathub (Fedora, Mint flatpak, elementary secondary) | Flathub API v2 / raw catalog | `https://flathub.org/api/v2/appstream/<id>` (JSON incl. `screenshots`); raw: `https://dl.flathub.org/repo/appstream/x86_64/appstream.xml.gz` |
| Ubuntu (deb) | DEP-11 | `http://archive.ubuntu.com/ubuntu/dists/<series>/<component>/dep11/Components-amd64.yml.gz`; media at `https://appstream.ubuntu.com/media/<series>/<relative-url>` |
| Ubuntu (snap) | Snap Store API | `https://api.snapcraft.io/v2/snaps/info/<snap>?fields=media` — header `Snap-Device-Series: 16` is **mandatory** |
| Debian (Mint fallback) | DEP-11 + community uploads | `https://deb.debian.org/debian/dists/<suite>/main/dep11/…`; `https://screenshots.debian.net/json/package/<pkg>` |
| Linux Mint (deb) | community uploads, one PNG per package | `https://community.linuxmint.com/img/screenshots/<aptname>.png`; full Apache autoindex at `…/img/screenshots/` (~7 950 files) — scrape the index once instead of HEAD-probing |
| elementary AppCenter | curated flatpak repo | `https://flatpak.elementaryos.org/repo/appstream/x86_64/appstream.xml.gz` (182 components; `flatpak.elementary.io` 301-redirects here) |

Format notes:

- **Catalog XML** (`<components version="0.8">`): per screenshot, one
  `<image type="source">` (upstream original) and several
  `<image type="thumbnail">` (distro resizes). If the root has
  `media_baseurl`, image URLs are relative to it.
- **DEP-11 YAML** (Debian/Ubuntu): multi-document; header doc carries
  `MediaBaseUrl`, per-component `Screenshots:` with relative `url`s.
  `CID-Index-amd64.json.gz` maps component-id → media path directly.
- Fedora rpm payloads are zstd cpio — extract with `rpm2cpio | cpio` (modern)
  or `bsdtar -xf`.

## ID normalization (the join key)

Canonical key: **AppStream component-id with a trailing `.desktop`
stripped** (`org.kde.kcalc`). Rules, all verified:

- Legacy `.desktop`-suffixed ids appear in Fedora, Debian/Ubuntu DEP-11, the
  Flathub *raw* catalog and snap `common-ids`; the Flathub *API* uses the
  stripped form. Query both forms; store the stripped one.
- component-id ↔ deb/rpm package name: `<pkgname>` (XML) / `Package:`
  (DEP-11) inside the catalogs themselves.
- component-id ↔ snap name:
  `api.snapcraft.io/v2/snaps/find?common-id=<id>&fields=media,common-ids` —
  works but sparse; fall back to name matching.
- Mint is keyed by **APT package name**, not component-id — resolve through
  the Debian/Ubuntu DEP-11 `Package:` field.
- Last resort for package-name joins: `https://repology.org/api/v1/project/<name>`
  (set a real User-Agent, ≤1 req/s).

## Corpus layout

```
corpus/
  index.json                     one entry per (app, distro, source)
  media/<app-id>/<distro>/<source>/<n>-<sha256-prefix>.png
```

`index.json` entry (append-only; a re-fetch adds a new entry rather than
overwriting, so staleness over time stays observable):

```json
{
  "app_id": "org.kde.kcalc",
  "distro": "fedora",              
  "source": "fedora-thumbnails",   
  "source_url": "http://dl.fedoraproject.org/pub/alt/screenshots/f44/752x423/…png",
  "kind": "thumbnail",             
  "width": 752, "height": 423,
  "fetched": "2026-08-15T12:00:00Z",
  "sha256": "…",
  "file": "media/org.kde.kcalc/fedora/fedora-thumbnails/1-ab12cd.png",
  "pkgname": "kcalc",
  "notes": null
}
```

Flat JSON index first; move to SQLite only if it gets slow. The comparison
dataset of TODO §2 is a view over this index (one row per app, one column per
distro, plus our own captures).

## Pilot app set

Start with ~10 apps that exist across all four ecosystems and have known
staleness stories, e.g.: `org.kde.kcalc` (already our POC app), `org.gimp.GIMP`,
`org.inkscape.Inkscape`, `org.videolan.VLC`, `org.audacityteam.Audacity`,
`org.blender.Blender`, `org.gnome.gedit` or GNOME Text Editor, `org.kde.okular`,
`org.libreoffice.LibreOffice`, `com.transmissionbt.Transmission`. Verify each
resolves in every source before freezing the list; expand to full-catalog
scale only after the pipeline works.

## Collectors (one module per source)

All live under `collect/`, share the index-writing code, and are idempotent
(skip when sha256 already indexed for the same source URL and date window).

- [ ] `collect/fedora.py` — download + unpack appstream-data rpm, parse
  `fedora.xml.gz`, fetch **thumbnail** URLs (the `source` URLs point at
  arbitrary upstream hosts and rot; keep them as metadata only).
- [ ] `collect/flathub.py` — API v2 per app id; covers Fedora flatpaks
  (their component-ids match upstream), Mint's flatpak path, and elementary's
  secondary source.
- [ ] `collect/ubuntu_dep11.py` — newest series' `Components-amd64.yml.gz`
  (main + universe); join `MediaBaseUrl`.
- [ ] `collect/snap.py` — `snaps/info` + `find?common-id=`, mandatory
  `Snap-Device-Series: 16` header.
- [ ] `collect/debian.py` — DEP-11 for the current stable suite, plus
  `screenshots.debian.net/json/package/<pkg>` (Mint's fallback source).
- [ ] `collect/mint.py` — scrape the autoindex once, then fetch
  `<aptname>.png` for apps in the set.
- [ ] `collect/elementary.py` — parse the AppCenter flatpak catalog; fetch
  repo-hosted media and record (but don't rely on) `raw.githubusercontent.com`
  source URLs.
- [ ] `collect/all.py` — run everything for the pilot set, write
  `corpus/index.json`; this becomes the core of the one-command refresh
  (TODO §7).

## Pitfalls (all verified 2026-08-15)

- `appstream.ubuntu.com` currently serves an **expired TLS cert** (since
  2026-07-31) and has **pruned media for older series** (noble 404s where
  resolute serves). Prefer the newest series; tolerate cert failure
  explicitly and note it in provenance.
- Flathub media URLs embed a content hash that changes on metadata updates —
  never cache URLs, always re-resolve via API/catalog.
- Mint images can be 15+ years stale (that is the point of this project —
  record it, don't “fix” it in the collector).
- screenshots.debian.net is community-uploaded with coverage gaps; Debian's
  own store UIs render DEP-11 media, so collect both and label them as
  distinct sources.
- elementary's repo host moved (`flatpak.elementary.io` →
  `flatpak.elementaryos.org`); follow redirects.

## Milestones

- [ ] **M0** — corpus layout + index writer + id-normalization helper, with
  tests against the known KCalc quirks (`.desktop` suffix in/out).
- [ ] **M1** — Fedora + Flathub collectors working for the pilot set
  (these two are the best-behaved sources).
- [ ] **M2** — Ubuntu DEP-11 + Snap + Debian + Mint + elementary collectors.
- [ ] **M3** — `collect/all.py` one-command run; document in README; freeze
  the pilot-set output as the first dated corpus snapshot.
- [ ] **M4** — cross-distro mapping table (feeds TODO §2's comparison
  dataset).

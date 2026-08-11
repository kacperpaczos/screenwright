# Where software centres get their screenshots

Established 2026-08-10 against mintinstall @ 750f52a and Fedora 44 with
AppStream 1.1.3 and Discover 6.7.3.

## Linux Mint: mintinstall

The relevant code is `usr/lib/linuxmint/mintinstall/imaging.py`, class
`ScreenshotDownloader`. It takes two entirely different paths depending on the
package type.

### Flatpak packages

Identified by `pkginfo.pkg_hash` starting with `f`. Screenshots come from
AppStream metadata, with relative addresses prefixed by
`FLATHUB_MEDIA_BASE_URL = "https://dl.flathub.org/media/"`. Nothing is hosted by
Mint; the source of truth is the project's own `metainfo.xml`.

### Deb packages

Sources are tried in order, up to four images in total:

1. **Mint's own** — `https://community.linuxmint.com/img/screenshots/<pkgname>.png`.
   Exactly one image, named after the package, probed with `requests.head`.
2. **Debian** — HTML scraping of `https://screenshots.debian.net/package/<pkgname>`
   with BeautifulSoup and the regex `/shrine/screenshot[/\d\w]*large-[\w\d]*.png`.
3. **hamonikr.org** — optional, behind the `HAMONIKR_SCREENSHOTS` setting.

Images are cached at `~/.cache/mintinstall/screenshots/<pkgname>_<n>.png`, with
`n` starting at 1.

**mintinstall has no upload path at all.** It is purely a consumer; uploading
happens through the community.linuxmint.com web service.

## Fedora

The catalogue is `/usr/share/swcatalog/xml/fedora.xml.gz`, shipped by the
`appstream-data` package. On F44, 1903 of 2364 components carry screenshots,
roughly 80 percent.

Every `<screenshot>` holds:

- `<image type="source">` — the upstream URL, pointing at the project's own
  site, git forge or CDN.
- `<image type="thumbnail">` in four sizes, mirrored by Fedora:

```
http://dl.fedoraproject.org/pub/alt/screenshots/f44/<WIDTH>x<HEIGHT>/<Name>-<hash>.png
```

The sizes are `112x63`, `224x126`, `624x351` and `752x423`. The filename is
`<ComponentName>-<hash>.png`, where the hash appears to be an md5 of the source
URL.

Most common source domains: dl.fedoraproject.org (11296), cdn.kde.org (336),
raw.githubusercontent.com (329), gitlab.gnome.org (263).

**Fedora does not take its own screenshots.** `appstream-generator` fetches
whatever upstream declared in `metainfo.xml`, generates thumbnails and re-hosts
them.

## The structural conclusion: two regimes

| Regime | Who decides the image | Where a fix goes |
|---|---|---|
| **Metainfo-driven** — Fedora, Flathub, Mint/flatpak, Ubuntu's newer stack | upstream, in `metainfo.xml` | a pull request per project |
| **Community-uploaded** — Mint/deb (community.linuxmint.com), screenshots.debian.net | any user | the service's upload form |

This is what determines whether the project is feasible at all. Generating an
image is easy. The question is where to put it so that anyone sees it, and the
answer differs completely between the two regimes.

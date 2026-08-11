# Verification log

End-to-end test on Fedora 44 KDE, AppStream 1.1.3, Discover 6.7.3, 2026-08-10.

## Result

Replacing the whole component worked. After
`sudo appstreamcli refresh --force`, `appstreamcli dump org.kde.kcalc.desktop`
returned our five `127.0.0.1:8899` URLs for the rpm variant. The flatpak variant
kept its Flathub images, which is correct: it is a separate component from a
different origin, and the override does not target it.

Discover, started under Xvfb on `appstream://org.kde.kcalc.desktop`, showed the
application page with the source "From Fedora Linux" and a single screenshot in
place of the four upstream ones from cdn.kde.org. The local image server logged
`GET /kcalc-752x423.png` returning 200, and the displayed image matches
`poc/media/kcalc-752x423.png` pixel for pixel, letterboxing included.

Evidence: `poc/discover-kcalc.png`.

Discover required no rebuild. A catalogue file plus a cache refresh was enough.
It does have to be restarted, because it reads the AppStream pool at startup.

## What this does and does not prove

It proves the substitution mechanism: an image produced locally can be made to
appear in a real software centre, on a real system, without patching the store.

It does not prove anything about delivery. The override lives in a root-owned
directory on one machine. Getting an image in front of other people still means
either a pull request to the upstream project (metainfo-driven stores) or an
upload to a community service (Mint's deb path, screenshots.debian.net). See
[where-screenshots-come-from.md](where-screenshots-come-from.md).

## Environment notes

The test system carried `XDG_DATA_HOME='%h/.local/share'` — a literal,
unexpanded specifier. The visible symptom was `%h` directories created in seven
different places.

A fresh login shell has the variable unset, so the configuration itself is
already fixed, but the running graphical session and everything launched from it
still carry the bad value until logout. This matters here because anything
driven by XDG paths and started from that session will read and write in the
wrong directory; `shoot.py` therefore overrides `XDG_DATA_HOME` explicitly for
the applications it launches.

## Cleanup

    sudo rm /usr/share/swcatalog/xml/90-screenwright.xml
    sudo appstreamcli refresh --force
    poc/serve.sh stop

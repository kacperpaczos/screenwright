# Protokół dostarczania zrzutów: per platforma, nie per sklep

Rozszerzenie `store-screenshot-delivery.md` o pomiar na pełnych katalogach
zebranych z wnętrza dystrybucji (2026-08-22, `collectors.md`).

**Pytanie:** czy dostarczanie zrzutów jest per dystrybucja, per platforma
(apt/rpm/flatpak/snap), czy per sklep?

**Odpowiedź:** **per platforma** — a dla formatów natywnych dystrybucji (apt, rpm)
także **per dystrybucja**. Sklep (GNOME Software / Discover / mintinstall) tylko
czyta katalog AppStream i nie wnosi własnego źródła; wyjątkiem jest snap-store,
bo snap jest osobną platformą-sklepem.

## Dane (z wnętrza Fedory 44 i Ubuntu 24.04)

| Platforma — źródło | host obrazów | aplikacje | zrzuty |
| --- | --- | ---: | ---: |
| rpm — Fedora AppStream (`fedora.xml.gz`) | `dl.fedoraproject.org` + upstream (github, gitlab, cdn.kde.org) | 1 903 | 12 631 |
| deb — Ubuntu DEP-11 | `appstream.ubuntu.com` (Canonical rehostuje wszystko) | 821 | 5 072 |
| flatpak — Flathub | `dl.flathub.org` (identycznie na Fedorze i Ubuntu) | 3 326 | 41 744 |
| snap — snapd `/v2/find` | `dashboard.snapcraft.io` | 1 160 | 3 421 |

Razem 62 868 zrzutów / 6 186 aplikacji.

## Dowód „ta sama aplikacja, inny kanał"

- 739 aplikacji występuje w ≥2 formatach.
- **496** aplikacji jest jednocześnie w katalogu rpm (Fedora) i deb (Ubuntu);
  **496/496 (100%)** ma **inny host zrzutu** — Fedora zostawia URL upstream/mirror,
  Ubuntu rehostuje na `appstream.ubuntu.com`.
- flatpak: ten sam Flathub-owy AppStream pojawia się identycznie na obu
  dystrybucjach (deduplikacja po URL scala go w jeden) → per platforma.

## Sklep tylko czyta katalog (kod z submodułów)

- GNOME Software: `gs_app_get_screenshots()` → AppStream (`lib/gs-appstream.c`).
- KDE Discover: `AppStreamUtils::fetchScreenshots()` (PackageKitBackend).
- mintinstall: AppStream/flatpak → cache `~/.cache/mintinstall/screenshots`.
- snap-store: snapd → `dashboard.snapcraft.io` (osobna platforma).

Discover i GNOME Software na tej samej Fedorze zwracają dla aplikacji bajtowo
identyczne URL-e (Etap 0) — bo oba czytają `fedora.xml.gz`. Zmiana pulpitu
(GNOME/KDE) ani sklepu nie zmienia zrzutów; zmiana dystrybucji lub formatu — tak.

## Konsekwencja dla podmiany (cel 2)

Override trzeba robić **per platforma × dystrybucja**: osobno dla katalogu rpm
Fedory, osobno dla DEP-11 Ubuntu; flatpak i snap mają własne, scentralizowane
kanały (Flathub / snapcraft), na które override AppStream nie wpływa — snap
pozostaje poza zasięgiem (asercja `store`, patrz `snap-store-diagnostics.md`).

## Zastrzeżenie

`appstream.ubuntu.com` serwuje wygasły certyfikat TLS (od 2026-07-31) — treść
zrzutów deb jest dziś nieosiągalna po HTTPS (awaria Canonical; te zrzuty nie
ładują się też w sklepach na Ubuntu). URL-e są w indeksie, bajty do dociągnięcia
po naprawie po stronie Canonical.

## Linia odtworzenia

`docs/collectors.md` — jak zebrać; `python -m cli collect --source guest
--hydrate-media N` — dociągnięcie bajtów na hosta do `corpus/media/`.

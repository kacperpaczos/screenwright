# Jak sklepy dostarczają screenshoty — pomiar na żywych maszynach

Ustalone empirycznie 2026-08-18 na trzech VM-kach zbudowanych przez
`vm/build/` i uruchomionych przez `qemu:///session`. Każda liczba i URL
poniżej pochodzi z realnego przebiegu, nie z dokumentacji.

Metoda: klon golden image'a → autologin → komenda **z naszego drivera**
(`UbuntuDriver`, `GnomeSoftwareDriver`, `DiscoverDriver`) → `virsh screenshot`
→ `appstreamcli dump org.gimp.GIMP` + sonda `curl` z wnętrza gościa.

Zrzuty ekranu z tego pomiaru leżą w
[`docs/media/store-delivery-2026-08-18/`](media/store-delivery-2026-08-18/):

| Plik | Co pokazuje |
| --- | --- |
| `fedora-ws-gnome-software-gimp.png` | GNOME Software, karuzela z **wyrenderowanymi** screenshotami |
| `fedora-kde-discover-gimp.png` | Discover, cztery screenshoty w karuzeli, „Install from Fedora Linux" |
| `ubuntu-snap-store-gimp.png` | snap-store, **puste sloty** — wygasły certyfikat `appstream.ubuntu.com` |
| `ubuntu-gnome-software-gimp.png` | GNOME Software na Ubuntu, ten sam objaw |
| `*-desktop.png` | czysty pulpit po autologinie, przed otwarciem sklepu |
| `*-PRZED-poprawka-chromu.png` | stan sprzed wyłączenia kreatorów pierwszego uruchomienia — dla porównania |

## Wynik

| Środowisko | Sklep | Źródło metadanych | Host mediów | Screenshoty |
| --- | --- | --- | --- | --- |
| Fedora 44 WS | GNOME Software 50.0 | `/usr/share/swcatalog/xml/fedora.xml.gz` | `dl.fedoraproject.org` | ✅ pobrane i wyrenderowane |
| Fedora 44 KDE | Discover 6.6.4 | **ten sam** `fedora.xml.gz` | **te same URL-e, ten sam md5** | ✅ pobrane i wyrenderowane |
| Ubuntu 24.04 (źródło: deb) | GNOME Software 46 / App Center | DEP-11 YAML w `/var/lib/app-info/yaml` | `appstream.ubuntu.com` | ❌ **wygasły certyfikat TLS** |
| Ubuntu 24.04 (źródło: snap) | snap-store 1390 | snapd → `api.snapcraft.io` | `dashboard.snapcraft.io` | ✅ osiągalne (312 kB) |

## Trzy wnioski

### 1. Silnik sklepu nie ma znaczenia — liczy się pula metadanych

Discover i GNOME Software na Fedorze zwracają dla `org.gimp.GIMP`
**bajtowo identyczne** URL-e, z tym samym skrótem:

```
http://dl.fedoraproject.org/pub/alt/screenshots/f44/624x351/org.gimp.GIMP-7eae94e695e89fa68c5b7f52bf229cd4.png
```

Oba czytają tę samą pulę AppStream. Różny toolkit (Qt vs GTK) i różny
kod sklepu nie przekładają się na różnicę w dostarczaniu obrazów.

### 2. Dystrybucja ma znaczenie — ten sam sklep, inne wszystko

GNOME Software na Ubuntu i na Fedorze to ten sam program, a mimo to:

| | Fedora 44 | Ubuntu 24.04 |
| --- | --- | --- |
| format katalogu | XML (`fedora.xml.gz`) | **DEP-11 YAML** (`/var/lib/app-info/yaml`) |
| wersja AppStream | 1.1.0 | 1.0.2 |
| host mediów | `dl.fedoraproject.org` | `appstream.ubuntu.com` |
| nazewnictwo | `<id>-<md5>.png`, katalog per rozmiar | `image-N_<WxH>@1.png`, katalog per komponent |
| rozmiary | 112×63 … 1504×846 (7 wariantów) | 224×126 … 1248×702 + `_orig` |

Czyli **sklep jest tylko przeglądarką; treść dowozi dystrybucja**. Override
trzeba budować per dystrybucja, nie raz na sklep.

### 3. Format pakietu przebija jedno i drugie

Wpis snapowy w ogóle nie przechodzi przez AppStream — snap-store pyta snapd,
snapd pyta `api.snapcraft.io`, media lecą z `dashboard.snapcraft.io`. Żaden
override katalogu AppStream tego nie dotknie.

## Uwaga: `appstream.ubuntu.com` ma dziś wygasły certyfikat

To nie jest nasz błąd ani właściwość sklepu — to **awaria po stronie
Canonical**, trwająca w dniu pomiaru:

```
subject=CN=appstream.ubuntu.com
issuer=C=US, O=Let's Encrypt, CN=R13
notBefore=May  2 11:13:33 2026 GMT
notAfter=Jul 31 11:13:32 2026 GMT      ← wygasł 18 dni przed pomiarem
```

```
curl:      (60) SSL certificate problem: certificate has expired
curl -k:   http_code=200 bytes=224425      ← plik JEST, blokuje wyłącznie certyfikat
```

Skutek: na Ubuntu żaden sklep czytający AppStream nie pokaże dziś screenshotów
appek deb. **Ikony działają**, bo są lokalne
(`/var/lib/app-info/icons/ubuntu-noble-universe/48x48/gimp_gimp.png`) —
i to jest pułapka interpretacyjna: widok „ikona jest, screenshotów nie ma"
wygląda jak problem sklepu, a jest problemem jednego certyfikatu.

Praktyczne konsekwencje:

- Porównania „czy nasz screenshot się pokazał" na Ubuntu są **dziś
  niemiarodajne** dla ścieżki deb — trzeba poczekać na odnowienie certyfikatu
  albo serwować media z własnego hosta (co i tak robimy w override).
- Nasz własny serwer (`cli serve`) tego problemu nie ma, więc override
  wskazujący na `127.0.0.1:8899` zadziała niezależnie od stanu CDN-u Canonical.

## Co z tego wynika dla override'u

Potwierdza wcześniejszą decyzję (override AppStream zamiast snap-store-proxy)
i zawęża ją:

- **Jeden override na dystrybucję**, nie na sklep. Fedora i Ubuntu wymagają
  osobnych plików katalogu.
- `domains/override/catalog.py` czyta dziś tylko `*.xml.gz`
  (`GzipXmlCatalogLoader`). Dla Fedory to wystarcza. Dla Ubuntu źródłem jest
  DEP-11 YAML — ale Ubuntu **ma** też `/usr/share/swcatalog/xml/`, więc nasz
  override w XML-u prawdopodobnie się wpisze mimo innego formatu źródła.
  **Niezweryfikowane** — to następny eksperyment.
- Appki snapowe zostają poza zasięgiem override'u. Jeśli mają być w zakresie,
  wraca temat snap-store-proxy razem z jego blokadą (asercja `store`).

## Powtórzenie pomiaru

```bash
vm/build/build-keypair.sh
vm/build/install-fedora.sh ws
vm/build/install-fedora.sh kde
vm/build/seed-ubuntu.sh
python -m cli vm ssh <domena> -- appstreamcli dump org.gimp.GIMP
```

Sondy użyte wyżej są w `vm/scripts/diagnose-ubuntu.sh` (sekcje `media_probe`
i `media_fetch`); parser wyłuska z nich `screenshot_urls`.

# Diagnostyka snap-store w VM Ubuntu

Dokument opisuje format raportu produkowanego przez
`vm/scripts/diagnose-ubuntu.sh` (zbieranie przez SSH) i
`vm/scripts/diagnose_ubuntu.py` (parser), oraz to, czego dowiedzieliśmy się
z pierwszego realnego przebiegu.

## Uruchomienie

```bash
python -m cli vm diagnose <nazwa-domeny> --output vm/reports/diagnose-ubuntu.json
python -m cli vm diagnose <nazwa-domeny> --print          # JSON na stdout
```

Wymaga działającej domeny, `qemu-guest-agent` w gościu (lookup IP przez
`virsh domifaddr --source agent`) i pary kluczy z `vm/build/build-keypair.sh`.

## Format wejściowy

Skrypt zbierający zrzuca sekcje oddzielone markerami; parser nie zna
poszczególnych komend, tylko ten protokół:

```
===SECTION:<name>===
...dowolna zawartość...
===END_SECTION===
```

Zbierane sekcje: `snapd_version`, `snap_store_info`, `snap_changes`,
`snap_store_cache`, `snapd_journal`, `api_probe`, `media_probe`.

## Format wyjściowy

| Pole | Znaczenie | Jak czytać |
| --- | --- | --- |
| `snapd_version` | wersja z `snap version` | pusty ⇒ snapd nie odpowiedział |
| `snap_store_channel` | pole `tracking:` z `snap info snap-store` | **pusty ⇒ snap-store NIE jest zainstalowany** (`snap info` dla niezainstalowanego snapu pokazuje metadane ze store'u, ale bez `tracking`) |
| `snap_store_version` | pole `version:` | jw. |
| `api_endpoints` | URL-e `api.snapcraft.io` z journala i `ss -tnp` | czym snapd realnie gada |
| `cache_file_count` | liczba plików w `~/.cache/snap-store` | **0 ⇒ GUI sklepu nigdy nie wystartowało** |
| `media_url_hints` | URL-e wyłuskane z `media_probe` | patrz pułapka niżej |
| `raw` | surowe sekcje | do ręcznej analizy |

### Pułapka: `media_url_hints` to nie są screenshoty

Sonda `media_probe` woła `GET /v2/snaps/info/snap-store` i wyciąga z
odpowiedzi wszystkie URL-e `api.snapcraft.io`. W praktyce dominują tam
`download.url` z `channel-map`, czyli **pliki `.snap`**, a nie media.
Screenshoty siedzą w `snap.media[]` i mają postać
`https://api.snapcraft.io/api/v1/snaps/screenshots/<snap-id>/<plik>.png`.
Niepusty `media_url_hints` nie dowodzi więc, że cokolwiek pobraliśmy.

## Wynik pierwszego realnego przebiegu (2026-08-18)

Domena z ówczesnego golden image'a `ubuntu-24.04.qcow2`. Sam raport nie jest
w repo — `vm/reports/` to katalog wyjściowy przebiegów i jest ignorowany przez
gita; poniżej wypisane pola to wszystko, co z niego wynikało:

- `snapd_version` działa, journal zdrowy (snapd 2.76+ubuntu24.04.1),
- `snap_changes` = tylko „Initialize system state" ⇒ **żaden snap nie był instalowany**,
- `snap_store_channel` = `""` ⇒ **snap-store nieobecny**,
- `cache_file_count` = 0 ⇒ **GUI nigdy nie ruszyło**,
- `media_url_hints` = wyłącznie URL-e `.snap` (patrz pułapka wyżej).

Przyczyna: golden image był zbudowany z **serwerowego** cloud image'a
(`noble-server-cloudimg-amd64.img`), a NoCloud seed nie był podpięty do
domeny, więc cloud-init nie zaaplikował user-data. Naprawione:
`vm/build/seed-ubuntu.sh` zapisuje seed ISO trwale, `DistroSpec.seed_iso`
podpina je jako cdrom, a user-data instaluje `ubuntu-desktop-minimal`
+ `snap-store` i włącza autologin.

## Ograniczenia

### `proxy.store` nie przyjmuje URL-a

`domains/matrix/store_proxy.py` odwzorowuje kształt Snap Store API v2, ale
**nie ma dziś zweryfikowanej ścieżki wpięcia go w snapd**:

- `snap set core proxy.store=<wartość>` przyjmuje *identyfikator store'a*,
  nie URL. Samo `http://10.0.2.2:8900` nie zadziała.
- URL snapd rozwiązuje z podpisanej asercji `store` (pole `url`), którą
  trzeba wcześniej `snap ack`. Asercja musi być podpisana kluczem konta
  brand — czego nie mamy.
- Do tego nie znamy realnych `snap-id` pilot-appek, więc
  `POST /v2/snaps/refresh` (adresowany po id) i tak nie ma czym odpowiadać.

Dopóki to nie jest rozstrzygnięte, proxy nadaje się do testów kontraktu
HTTP, ale nie do podmiany screenshotów w realnym snap-store. Tańsza
alternatywa dla dowodu „pobrane → podmienione → widoczne w sklepie":
override katalogu AppStream (`python -m cli override`) + GNOME Software
lub Discover, które czytają lokalny katalog.

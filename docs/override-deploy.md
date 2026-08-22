# Cel 2: podmiana zrzutów w prawdziwym sklepie

Stan **2026-08-22 — ZAMKNIĘTE end-to-end, także wizualnie.** GNOME Software 50
na Fedorze WS renderuje w karuzeli **nasz** zrzut zamiast katalogowego.
Rola `ansible/roles/deploy-override`, kod `domains/override` (`patch_catalog`).

## Metoda, która działa: podmiana w SAMYM katalogu bazowym

Kluczowe odkrycie (zweryfikowane na żywo): **libappstream UNIONuje listy
`<screenshots>` komponentów o tym samym `<id>` z różnych katalogów.** Skutki:

- osobny plik override (`cli override` bez `--patch`, `priority=1`) tylko **DODAJE**
  nasz zrzut obok oryginału — `appstreamcli dump <id>` pokazuje 2 zrzuty, a sklep
  renderuje bazowy pierwszy;
- `merge="replace"` (nawet z `version="0.8"`, `type="desktop"`) jest **po cichu
  ignorowany** przez `appstreamcli refresh`/pool — wynik: tylko bazowy zrzut.

Jedyne, co daje „sklep pokazuje **wyłącznie** nasz zrzut", to **przepisanie bloku
`<screenshots>` docelowego komponentu wewnątrz katalogu bazowego**
(`/usr/share/swcatalog/xml/fedora.xml.gz`) i zapis całego katalogu z powrotem:

```bash
python -m cli override --patch \
  --id GameConqueror.desktop \
  --base-url http://127.0.0.1:8080 --prefix gimp \
  --catalog /path/to/fedora.xml.gz --out /path/to/fedora.xml.gz
```

`patch_catalog` (`domains/override/catalog.py`) czyta katalog, znajduje komponent
po `<id>`, usuwa jego `<screenshots>`, wstawia nasz blok (source + 4 miniatury),
zachowuje **wszystkie pozostałe komponenty** i zapisuje gz. Obsługuje katalogi
z domyślnym namespace (Fedora appstream-generator) i bez.

## Rola `deploy-override` (self-verifying)

1. wgranie obrazów + serwer mediów w gościu (`systemd-run --unit=swmedia --
   python3 -m http.server 8080`);
2. kopia zapasowa katalogu bazowego (`*.screenwright-orig`, idempotentnie);
3. **pobranie katalogu z gościa → `cli override --patch` na węźle sterującym →
   odesłanie** (jedno źródło prawdy = przetestowany kod domeny);
4. `appstreamcli refresh --force`;
5. **dwie asercje:** nasz `<prefix>-source.png` jest w `appstreamcli dump <id>`
   **oraz** komponent ma **dokładnie jeden** `<screenshot>` (nie union z oryginałem).

```bash
cd ansible && ansible-playbook playbooks/deploy-override.yml \
  -e override_component_id=GameConqueror.desktop -e override_prefix=gimp \
  -e '{"override_media": ["<abs>/gimp-source.png", "<abs>/gimp-624x351.png", ...]}'
```

## Dowód na trzech warstwach (2026-08-22)

1. **Dane (deterministyczne, niezależne od sklepu):** `appstreamcli dump
   GameConqueror.desktop` — czyli metadane, które czyta każdy sklep oparty na
   libappstream (GNOME Software, KDE Discover) — daje **dokładnie 1 zrzut = nasz**
   (`grep -c 8080` = 5 URL-i, `dl.fedoraproject` = 0). Nasz URL jest wkompilowany do
   `/var/cache/swcatalog/cache/en-US-os-catalog.xb`, który gnome-software mmapuje.
2. **Fetch (behawioralne):** instrumentowany serwer (`/var/tmp/swmedia-access.log`)
   loguje `GET /gimp-624x351.png` od GNOME Software — sklep czyta podmieniony
   katalog i pobiera **nasz** obraz z naszego serwera.
3. **Piksel na DWÓCH sklepach (ten sam patch katalogu rpm):**
   - **GNOME Software 50** (GTK): crimson frac **0.20**
     (`images/cel2/cel2-PROOF-store-shows-ours.png`).
   - **KDE Discover** (Qt): crimson frac **0.16**
     (`images/cel2/cel2-PROOF-discover-shows-ours.png`).
   Oba czytają ten sam `/usr/share/swcatalog` → **podmiana jest per platforma
   (katalog libappstream), nie per sklep.**

## Platformy: gdzie i jak podmieniać (protokół, zweryfikowany 2026-08-22)

`patch_catalog` / `cli override --patch` wykrywa format katalogu po treści i
obsługuje **oba** źródła, które sklepy libappstream czytają:

| Platforma | Katalog, który czyta sklep | Metoda override | Stan |
| --- | --- | --- | --- |
| **rpm** (Fedora) | `/usr/share/swcatalog/xml/fedora.xml.gz` (AppStream XML) | patch `<screenshots>` in-place | **piksel** na GNOME Software + KDE Discover |
| **deb** (Ubuntu) | `/var/lib/swcatalog/yaml/…dep11…yml.gz` (DEP-11 YAML) | patch `Screenshots:` in-place (URL-e absolutne → `MediaBaseUrl` pomijany) | **dane**: `appstreamcli dump` = nasz 1 zrzut (`screenshots=1`, `mediabaseurl_prepended=0`) |
| **flatpak** (Flathub) | osobny appstream per-remote | override w danych remote'u | poza zakresem patcha katalogu OS |
| **snap** | snapd REST / snap store API (`dashboard.snapcraft.io`) | brak — snap omija AppStream | granica: nie da się patchem katalogu |

**Ważny niuans (deb, zweryfikowany):** dla aplikacji **zainstalowanej**
gnome-software czyta LOKALNE `metainfo` aplikacji, nie pobrany katalog DEP-11 —
override katalogu wtedy nie zmienia karuzeli. Testować na aplikacji
**niezainstalowanej** (jedynym źródłem metadanych jest katalog). Na golden Ubuntu
24.04 gnome-software ma dodatkowo problem z ładowaniem zdalnych mediów (broken
także dla ikony aplikacji) — piksel deb niepotwierdzony środowiskowo, ale warstwa
danych (to, co renderuje każdy libappstream-store) jest jednoznaczna.

## Pułapki karuzeli GNOME Software (potwierdzone na żywo)

Nie są wadą podmiany — to specyfika klienta; potrzebne do powtarzalnego zrzutu:

- **pojedyncza instancja.** `gnome-software --details=<id>` do już-działającego
  procesu pokazuje STARY cache. Trzeba `gnome-software --quit` + `pkill -9` **przed**
  `rm -rf ~/.cache/gnome-software ~/.local/share/gnome-software`, dopiero potem
  `systemd-run --user gnome-software --details=<id>`.
- **modal „Enable Third Party"** zasłania karuzelę. Zdejmowany bez narzędzi gościa
  przez **`virsh -c qemu:///session send-key <dom> --codeset linux KEY_ESC`**
  (warstwa wejścia QEMU; `org.gnome.Shell.Eval` jest wyłączony).
- **zrzut:** `gnome-screenshot` przez `systemd-run --user` **wiesza się** (rc=124);
  `grim` **nie działa na Mutterze** (wymaga wlroots). Do zrzutu używać **`virsh
  screenshot`** (framebuffer VNC). Sesja graficzna ma pełne env
  (`WAYLAND_DISPLAY=wayland-0`, `DISPLAY=:0`), więc GUI z `systemd-run --user` się rysuje.
- **wariant dwuźródłowy.** Gdy aplikacja jest i jako rpm, i jako flatpak/Flathub,
  sklep może pokazać zrzut flatpaka (poza AppStream rpm). Patch katalogu rpm celuje
  w komponent rpm; dla flatpaka/snapa podmiana jest w ich kanałach (patrz niżej).
- gnome-software **re-enkoduje** pobrane zrzuty do cache — sha pliku w
  `~/.cache/gnome-software/screenshots` ≠ sha oryginału; porównywać **średni kolor**
  (`convert … -resize 1x1 txt:-`), nie sha.

## Konsekwencja (spójna z `screenshot-protocol.md`)

Podmiana przez katalog AppStream działa dla **rpm i deb** (per dystrybucja);
flatpak (Flathub) i snap mają własne, scentralizowane kanały poza zasięgiem
patcha katalogu. Skuteczna podmiana tego, co widzi użytkownik, jest więc **per
wariant/platforma**, którą sklep wyświetla — nie globalna.

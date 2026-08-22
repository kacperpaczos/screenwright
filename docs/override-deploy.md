# Cel 2: podmiana zrzutów w prawdziwym sklepie

Stan 2026-08-22 (Faza 4, increment 1). Rola `ansible/roles/deploy-override`.

## Co działa (zweryfikowane na Fedorze WS)

Wstrzyknięcie override AppStream (`priority=1`, wygenerowany przez
`cli override` z zebranego katalogu) do działającej dystrybucji:

1. wgranie `90-screenwright.xml.gz` do `/usr/share/swcatalog/xml/`,
2. serwer obrazów w gościu (`systemd-run -- python3 -m http.server`),
3. `appstreamcli refresh --force`.

**Dowód (self-verifying w roli):** `appstreamcli dump <id>` — czyli metadane,
które czyta sklep — zwraca **nasz** URL zrzutu zamiast katalogowego. Ponadto log
serwera pokazuje, że **GNOME Software pobrał nasz obraz po HTTP**
(`GET /gimp-source.png`). Rola kończy się asercją, że nasz URL jest w dump.

Uruchomienie:

```bash
python -m cli override --id <ID> --base-url http://127.0.0.1:8080 --prefix p \
  --priority 1 --catalog corpus/guest/fedora/**/fedora.xml.gz --out ov.xml
gzip -c ov.xml > ov.xml.gz
cd ansible && ansible-playbook playbooks/deploy-override.yml \
  -e override_component_id=<ID> -e override_xml_gz=<abs>/ov.xml.gz \
  -e '{"override_media": ["<abs>/p-source.png", ...]}'
```

## Co wymaga dopracowania (chrome sklepu, nie mechanizm)

Wizualne potwierdzenie w karuzeli (zrzut framebuffera pokazujący nasz obraz)
utrudnia chrome GNOME Software, nie sama podmiana:

- **domyślny wariant.** Dla aplikacji dostępnej i jako rpm, i jako flatpak
  (np. GIMP) GNOME Software domyślnie pokazuje **flatpaka** (źródło „Fedora
  Flatpaks") — z zrzutami Flathuba, poza zasięgiem override AppStream rpm.
  Żeby zmienić to, co widzi użytkownik, override musi celować w **wariant, który
  sklep wyświetla** (flatpak → poza AppStream; rpm → działa, gdy to jedyny albo
  wybrany wariant). Aplikacje tylko-rpm (597 w katalogu Fedory) pokazują wariant
  rpm od razu.
- **modal „Enable Third Party Software Repositories?"** zasłania karuzelę przy
  pierwszym uruchomieniu.
- **wygaszanie ekranu** (DPMS) gasi framebuffer po bezczynności — profil wizualny
  musi mieć wyłączone `idle-delay`/blank.
- **cache zrzutów** GNOME Software (`~/.cache/gnome-software`) trzeba wyczyścić,
  by przerysował po podmianie.
- **fokus okna.** `gnome-software --details=<id>` uruchomiony przez SSH aktywuje
  usługę, ale okno nie zawsze wychodzi na pierwszy plan — `virsh screenshot`
  łapie wtedy przegląd Aktywności, nie stronę sklepu.

### Próba wizualna 2026-08-22 (grim → gnome-screenshot) i wnioski

`grim` **nie działa na GNOME/Mutter** (wymaga `wlr-screencopy`, protokołu wlroots
— GNOME go nie ma). Na GNOME odpowiednikiem „zrzut w sesji" jest `gnome-screenshot`
albo D-Bus `org.gnome.Shell.Screenshot`. `grim` miałby sens dopiero, gdyby sklep
uruchamiać pod headless kompozytorem wlroots (`cage`/`sway --headless`) — ale to
już nie jest prawdziwe środowisko GNOME.

Wykonano kilka prób na Fedorze WS. Ustalone twardo:
- override trafia do metadanych sklepu — `appstreamcli dump <id>` zwraca nasz URL
  (count=5), powtarzalnie, także dla aplikacji tylko-rpm;
- w czystym przebiegu serwer mediów oddawał 200, a GNOME Software **pobrał nasz
  obraz** (`GET /gimp-source.png`).

Czego NIE udało się jeszcze złapać: piksela naszej karuzeli na zrzucie. Powody,
w kolejności ważności:
1. **serwer mediów w gościu musi być jednostką systemd** (`systemd-run
   --unit=swmedia …`) — proces w tle przez SSH (`nohup`/`setsid &`) ginie z
   zamknięciem kanału, a wtedy sklep dostaje 404 i nie ma czego pokazać;
2. `gnome-screenshot` trzeba odpalać **w kontekście sesji** (`systemd-run --user
   -- gnome-screenshot -f …`), nie gołym exec po SSH;
3. świeży boot (nie `managedsave`/restore) — restore zostawia nieświeże jednostki
   systemd i stan `/var/tmp`, co psuło serwer mediów;
4. aplikacja tylko-rpm (wariant rpm od razu; dla dwuwariantowych sklep pokazuje
   flatpaka), `first-run false` + `idle-delay 0` przed pierwszym startem sklepu,
   `rm -rf ~/.cache/gnome-software`.

To jest bounded harness (deterministyczny serwer + zrzut w sesji + świeży boot),
a nie wada mechanizmu podmiany. Domknięcie = zebranie tych czterech punktów w
jednym przebiegu i template-match z naszym znacznikiem.

### Wykonalny następny krok dla weryfikacji wizualnej

Zamiast walczyć z framebufferem i fokusem: robić zrzut **w sesji** przez
`grim` (Wayland) po SSH (łapie konkretne okno, nie cały ekran, i nie zależy od
tego, czy okno jest na wierzchu w chwili `virsh screenshot`), albo podnieść okno
przez `gdbus call ... org.gnome.Shell.Eval` przed `virsh screenshot`. Do tego
aplikacja tylko-rpm (wariant rpm od razu), `first-run false` i `idle-delay 0`
ustawione przed pierwszym startem sklepu, oraz czyszczenie `~/.cache/gnome-software`.

To są punkty „chrome" znane z Etapu 0 (TODO §6). Domknięcie wizualnej
weryfikacji = ich obsługa + porównanie template match; mechanizm podmiany jest
gotowy i zwersjonowany.

## Konsekwencja (spójna z `screenshot-protocol.md`)

Podmiana przez override AppStream działa dla rpm i deb (per dystrybucja); flatpak
(Flathub) i snap mają własne, scentralizowane kanały poza zasięgiem override.
Skuteczna podmiana tego, co widzi użytkownik, jest więc **per wariant/platforma**,
którą sklep wyświetla — nie globalna.

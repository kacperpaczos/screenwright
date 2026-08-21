# Matrix timing — hipoteza, pomiar, warm cache

Zapis pomiarów przebiegu matrycy VM (TODO §6) na potrzeby planu transformacji
(Etap 0 → Bramka A). Liczby pochodzą z `MatrixReport.timings` (pole dodane
w `shared/results.py`) oraz z ręcznych smoke'ów na żywych klonach.

Host: Fedora 44, libvirt 12.0.0, QEMU 10.2.2, virt-install 5.1.0, passt
2026-07, 8 rdzeni, 30 GiB RAM, `/home` na btrfs, wszystko na
`qemu:///session`. Klony: 4096 MiB / 2 vCPU (`DEFAULT_DOMAIN`), VNC,
virtio-gpu 2D, sieć usermode passt z przekierowanym portem SSH.

## Hipoteza (zapisana 2026-08-22, przed pomiarem bazowym)

Per dystrybucja, dla przebiegu z dwiema aplikacjami:

| Faza | Udział czasu (hipoteza) |
| --- | --- |
| boot → agent → sesja graficzna (`create` + `wait_agent` + `wait_session`) | 60–70 % |
| render sklepu (`launch` + `settle`) | 20–30 % |
| overlay + `verify` + `teardown` | < 10 % |

Wniosek, jeśli hipoteza się potwierdzi: warm cache (save/restore zamiast
bootu) jest właściwą pierwszą optymalizacją. Jeśli dominuje render sklepu —
plan trzeba przestawić (settle/launch, nie boot).

## Smoke na żywo — Fedora WS, 2026-08-22 (klon golden `fedora-ws.qcow2`, 6.1 GB)

Skrypt: `VirshBackend` + `domains/matrix/guest.py` wprost (ten sam kod, co
w runnerze), jeden klon, bez matrycy.

| Krok | Wynik |
| --- | --- |
| `qemu-img create` overlay | 0.01 s |
| `virsh create` | 0.1 s |
| agent odpowiada na `guest-exec true` | **13.3 s** po `create` |
| `loginctl list-sessions` | `test` ma sesję `user` na seat0 (tty2) + sesję `manager` — autologin działa |
| `runuser -u test -- …` z agenta | **`runuser: cannot set groups: Operation not permitted`** — każde wywołanie |
| `virsh save` (gość 4 GiB, `save_image_format = "zstd"` w `~/.config/libvirt/qemu.conf`) | **6.1 s**, plik stanu 1.02 GB |
| `virsh save-image-dumpxml` | **brak `<backingStore>`** w zapisanym XML-u (libvirt nie zapisuje wykrytego łańcucha) |
| `mv disk→base`, nowy overlay na `base`, `virsh restore --xml domain.xml state` | rc 0, **5.7 s**; żywy XML: `disk.qcow2 → base.qcow2 → golden` |
| agent po restore | odpowiada po 0.04 s |
| passt po restore | port SSH nasłuchuje; `ssh -p <port> test@127.0.0.1` działa (`uptime` gościa: „up 2 min" — stan wznowiony, nie przebootowany) |
| `virsh dominfo` po restore | `Persistent: no` — domena transient zostaje transient |
| zegar gościa po restore | 12 s za hostem |
| `virsh destroy` | domena znika z `list --all` |

Wnioski:

- **Warm cache jest wykonalny dokładnie w zaprojektowanym kształcie** (zamrożony
  `base.qcow2` + świeży `disk.qcow2` pod tą samą ścieżką + `restore --xml`).
  Restore + gotowy agent to ~6 s zamiast ≥13 s do samego agenta przy zimnym
  boocie (sesja graficzna dochodzi później — patrz pomiar bazowy).
- `runuser` z `qemu-guest-agent` nie może zmienić grup → uruchamianie sklepu w
  sesji użytkownika musi iść inną drogą (sonda wariantów niżej).

## Sonda launcherów — Fedora WS, 2026-08-22

Pytanie: jak z hosta uruchomić komendę GUI **w sesji graficznej** użytkownika
`test`? Wynik na klonie `fedora-ws`:

| Droga | Wynik |
| --- | --- |
| kontekst procesu z `guest-exec` | `system_u:system_r:virt_qemu_ga_t:s0`, `CapEff` pełne — ogranicza **SELinux**, nie capabilities |
| `runuser -u test -- …` (agent) | `cannot set groups: Operation not permitted` |
| `setpriv --reuid=test …` (agent) | `activate capabilities: Permission denied` |
| `su - test -c …` (agent) | `Failed to execute child process "su" (Permission denied)` |
| `systemd-run --uid=test …` (agent) | `Failed to start transient service unit: Access denied` |
| `systemd-run --user -M test@.host …` (agent) | `Connection reset by peer` |
| `getenforce`, `systemctl show qemu-guest-agent` (agent) | też odmowa; `getsebool -a` nie pokazuje żadnego `virt_qemu_ga_*` |
| **SSH jako `test`** (`ssh -p <port> test@127.0.0.1`, przez passt) | kontekst `unconfined_t`; `systemctl --user is-active graphical-session.target` = `active` **23 s po `create`**; `systemctl --user show-environment` ma `DISPLAY=:0`, `WAYLAND_DISPLAY=wayland-0`, `XDG_CURRENT_DESKTOP=GNOME`; `systemd-run --user --collect --quiet --wait -- gnome-software --quit` 2.4 s, `… -- gnome-software --details=org.gimp.GIMP` 0.5 s, proces widoczny jako `gnome-software.service` użytkownika |

Decyzja: **komendy w sesji idą przez SSH** (`GuestShell` → `SshShell`),
agent zostaje tylko od pingu. To jest krok 1.1 planu transformacji wciągnięty
do Etapu 0, bo bez niego nie ma czego mierzyć. Fallback w razie hosta bez
SSH: boolean SELinux dla agenta w golden image — niezbadany, niepotrzebny.

Czas do okna sklepu (ta sama maszyna, zimny start `gnome-software` z
`--details=org.gimp.GIMP` przez SSH): ekran **nie zmienia się przez 30 s**,
zmienia między 30 a 45 s (journal: `gnome-software.service` wystartował
22:38:56, pierwsze komunikaty `libEGL` z procesu o 22:39:44). Stąd `settle`
wymaga zmiany względem klatki sprzed uruchomienia, a `settle_timeout` = 120 s.
Na klatce po 60 s widać stronę GIMP-a, ale (a) GNOME zostaje w przeglądzie
Aktywności (okno jako miniatura workspace'a), (b) modal „Enable Third Party
Software Repositories?" przykrywa stronę — oba do załatwienia w golden image /
driverze (`org.gnome.software show-nonfree-prompt=false`, wyjście z
przeglądu), nie blokują pomiaru.

## Pomiar bazowy — Fedora WS, 2026-08-22 (zimny boot, bez warm cache)

`python -m cli matrix --spec <fedora-ws, 2 aplikacje> --execute --backend virsh`
(raport: `vm/reports/baseline-ws.json`, gitignored; klon 4096 MiB / 2 vCPU;
`gnome-software` uruchamiany przez SSH jako `--quit` + `--details=<id>`).

| Faza | Sekundy | Udział w `run_total` |
| --- | ---: | ---: |
| `create_overlay` | 0.05 | 0.1 % |
| `create` (`virsh create`) | 0.86 | 1.6 % |
| `wait_agent` | 11.24 | 21.2 % |
| `wait_shell` (SSH) | 1.22 | 2.3 % |
| `wait_session` (`graphical-session.target`) | 3.20 | 6.0 % |
| **`boot` razem** | **16.52** | **31.2 %** |
| `launch` kcalc (`--quit` 3.3 s + `--details`) | 3.74 | 7.1 % |
| `settle` kcalc (4 klatki) | 3.31 | 6.2 % |
| `launch` GIMP | 0.47 | 0.9 % |
| `settle` GIMP (27 klatek) | 28.42 | 53.6 % |
| `verify` ×2 | 0.22 | 0.4 % |
| `teardown` | 0.25 | 0.5 % |
| **`run_total`** | **52.99** | 100 % |

Hipoteza **obalona**: boot to 31 %, a render sklepu (`launch` + `settle`) 68 %.
Warm cache sam z siebie zdejmuje więc najwyżej ~16 s z 53 s (i dokłada ~6 s
restore + czekanie) — daleko od celu „≥3×". Dźwignią jest render:
`gnome-software` startuje na zimno przy **każdej** aplikacji, bo driver robi
`--quit` przed `--details`. Dwie konsekwencje do decyzji na Bramce A:

1. **driver GNOME Software bez `--quit`** — `--details` na działającej
   instancji tylko przełącza stronę (sekundy zamiast ~30 s);
2. **szablon warm z już uruchomionym sklepem** — save po pierwszym renderze
   sklepu, wtedy każda aplikacja to nawigacja, nie zimny start.

Uwaga do `settle` kcalc: 3.3 s i „changed", a zrzut pokazuje goły przegląd
GNOME — „zmianą" względem klatki bazowej był **przeskok zegara w górnym pasku**
(minuta), nie sklep. Skrót pliku jest za czuły; od tej pory klatki są
porównywane odległością pikselową (PIL): „zmiana" = > 2 % pikseli,
„stabilne" = < 0.1 % (`GuestWaits.change_threshold` / `stable_threshold`).
Porównanie z szablonem dalej nic nie mówi (tu brak szablonów: `passed=False,
score=0`).

## Warm cache — Fedora WS, 2026-08-22 (`--execute --backend virsh`, domyślny warm root)

Dwa przebiegi z tym samym specem (2 aplikacje). Pierwszy buduje szablon
(`warm: build`), drugi w niego trafia (`warm: hit`). Raporty: `vm/reports/warm-ws-{1,2}.json`.

| Faza | run 1 (build) | run 2 (hit) | baseline (cold) |
| --- | ---: | ---: | ---: |
| `create_overlay` | 0.06 | 0.01 | 0.05 |
| `create` | 0.81 | — | 0.86 |
| `wait_agent` | 11.26 (+0.0 po restore) | 0.04 | 11.24 |
| `wait_shell` | 1.60 | 0.21 | 1.22 |
| `wait_session` | 3.54 | 0.21 | 3.20 |
| `warm_save` (settle + `virsh save`) | 7.17 | — | — |
| `warm_restore` (`restore --xml`) | 4.05 | 2.71 | — |
| **`boot` razem** | **21.25** | **3.16** | **16.52** |
| `launch` ×2 | 1.34 | 1.74 | 4.21 |
| `settle` ×2 | 128.91 (2× limit, bez zmiany) | 127.65 (121 bez zmiany + 6.5 OK) | 31.73 |
| `run_total` | 159.4 | 132.9 | 53.0 |

Wnioski:

- **Ścieżka warm działa i jest tania**: trafienie to 3.2 s do gotowej sesji
  (restore 2.7 s + agent/SSH/sesja 0.45 s) zamiast 16.5 s zimnego bootu —
  ~5× na samym boocie; budowa szablonu kosztuje jednorazowo ~5 s ponad zimny
  boot (save 4 s + restore 4 s; plik stanu ~1 GB zstd).
- **Ale sklep po restore rysuje pierwsze okno dopiero po >120 s** (w zimnym
  boocie ~45 s): w obu przebiegach `settle` kcalc doszedł do limitu bez zmiany
  ekranu (dystans 0.0001 = zegar), a dopiero launch GIMP-a — ~122 s po
  pierwszym `--details` — dostał okno w 6.5 s. Strona GIMP-a była poprawna
  (z tym samym modalem). Przyczyna w trakcie badania (sonda po restore:
  mapowanie nowego okna, stderr `gnome-software`, journal).
- Netto run 2 jest **wolniejszy** od baseline (133 s vs 53 s) wyłącznie przez
  limit `settle`; po naprawie startu sklepu po restore spodziewany czas
  przebiegu 2-aplikacyjnego ≈ 3 s + 2×(launch + render).

## Sonda po restore — Fedora WS, 2026-08-22

Szablon z run 1 przywrócony ręcznie (`restore --xml` 2.9 s, gotowość 0.4 s);
zegar gościa 279 s za hostem (tyle, ile minęło od `save`).

| Krok | Wynik |
| --- | --- |
| `systemd-run --user -- gnome-calculator` | okno na ekranie po 3 s (dystans 0.19) — **nowe okna mapują się po restore normalnie** |
| `systemd-run --user --wait --pipe -- gnome-software --details=org.gimp.GIMP` | wraca po 0.2 s, pusto — akcja przekazana do **wznowionej instancji autostartu** (`gnome-software.service`, PID 2398, `--gapplication-service`, „active since" = start sesji szablonu) |
| ekran po `--details` | bez zmiany po 10 s, **okno sklepu po 20–30 s** (dystans 0.34) |

Wniosek: po restore sklep działa, a w przebiegach warm zgubiło start
**`--quit` tuż przed `--details`** w `GnomeSoftwareDriver`: `systemd-run --wait`
czeka na klienta `--quit` (0.1 s), nie na zgon instancji; `--details` trafia
do umierającego procesu i przepada. W zimnym boocie to samo `--quit` trwało
3.3 s (instancja autostartu jeszcze się nie zarejestrowała), więc wyścig nie
wychodził — za to każda aplikacja płaciła zimny start sklepu (~30–45 s).

Decyzje (wdrożone):

1. **`GnomeSoftwareDriver` bez `--quit`** — `--details` na działającej instancji
   przełącza stronę; bez instancji staje się nią sam.
2. **Rozgrzewka sklepu w szablonie**: `StoreDriver.warmup_commands()`
   (`gnome-software` / `plasma-discover` / `snap-store`) uruchamiane przed
   `virsh save`, z czekaniem na zmianę ekranu — w szablonie sklep jest już
   wyrenderowany, po restore każda aplikacja to nawigacja.

Pomiar po zmianach — niżej.

## Pomiar po poprawkach — 2026-08-22 (driver bez `--quit`, rozgrzewka w szablonie)

Uwaga do metody: „hit" z `warm-ws-4` okazał się **buildem** — zabity w locie
wcześniejszy przebieg zostawił działającą domenę `sw-fedora-ws-warm`, jej port
SSH był zajęty, więc `lookup()` zgłosił chybienie (`ssh port busy`) i szablon
został odbudowany. Logika chybienia zadziałała, hit WS mierzony jest niżej
jeszcze raz.

### Fedora WS

| Faza | `cold-ws-2` (zimny, bez `--quit`) | `warm-ws-3` (build + rozgrzewka) |
| --- | ---: | ---: |
| `boot` (create + agent + SSH + sesja) | 15.45 | 16.2 |
| `warm_save` (rozgrzewka + settle + save) | — | 7.53 |
| `warm_restore` + gotowość po restore | — | 2.95 + 0.75 |
| `launch` kcalc / `settle` kcalc | 0.62 / 3.26 (dystans 1.0) | 0.36 / 4.45 (0.52) |
| `launch` GIMP / `settle` GIMP | 0.27 / 29.87 | 0.27 / 57.98 |
| `run_total` | **49.8** | 91.0 (w tym jednorazowy build) |

`ready.png` z buildu pokazał **przegląd GNOME bez okna sklepu**: rozgrzewka
„zmieniła ekran" po ~3 s (GNOME zwija przegląd Aktywności przy starcie
aplikacji — zmiana całego ekranu, potem stabilność), a okno przyszło dopiero
30–45 s później — czyli `save` poszedł za wcześnie, a „szybkie" 3.3 s settle
kcalc w zimnym biegu (dystans 1.0) to to samo zwinięcie przeglądu, nie sklep.
Stąd **sonda okna** `StoreDriver.window_probe()` (GNOME Shell
`org.gnome.Shell.Introspect.GetWindows`, Ubuntu: snap-store): settle nie kończy
się, dopóki sonda nie powie `yes`. Pomiar WS po tej zmianie — niżej.

### Fedora KDE (Discover, bez sondy okna)

| Faza | `warm-kde-1` (build) | `warm-kde-2` (hit) |
| --- | ---: | ---: |
| `boot` | 17.9 | — |
| `warm_save` | 14.02 | — |
| `warm_restore` + gotowość | 5.56 + 0.52 | 5.57 + 0.46 |
| `launch` + `settle` kcalc | 0.36 + 3.32 | 0.27 + 3.28 |
| `launch` + `settle` GIMP | 0.38 + 21.47 | 1.71 + 20.34 |
| `run_total` | 64.0 | **32.1** |

- Hit KDE: **6 s do gotowej sesji** (restore 5.6 s — plik stanu większy niż na
  WS) i 32 s na dwie aplikacje.
- Zrzut Discovera po restore: okno z „Loading…", „Updates (Fetching…)" i
  modalem **„Update Issue"** (znany punkt TODO) — settle uznał stabilny ekran
  ładowania za gotowy; Discover nie ma sondy okna/treści. Render Discovera
  to osobny temat (PackageKit, modal), nie warm cache.
- `cold-kde-1` **padł**: overlay zimnego klona leżał w `work_root=/tmp/…`
  (tmpfs); PackageKit zapełnił go w minutę → `IO error … Disk quota exceeded`
  → VM stanęła → `virsh screenshot` zwracał błąd. Naprawione: `work_root`
  domyślnie `<image_root>/runs` (`--work-root`). Zimny KDE mierzony jeszcze raz
  niżej.

### Ubuntu 24.04 (App Center / snap-store)

| Faza | `cold-ubuntu-1` | `warm-ubuntu-1` (build) | `warm-ubuntu-2` (hit) |
| --- | ---: | ---: | ---: |
| `wait_agent` | 5.12 | 5.12 | 0.03 |
| `wait_shell` (SSH) | **119.96** | **120.02** | 0.30 |
| `wait_session` | 3.61 | 3.65 | 0.27 |
| `warm_save` (rozgrzewka `snap-store` + settle + save) | — | 17.21 | — |
| `warm_restore` | — | 4.09 | 3.71 |
| `settle` kcalc / GIMP | 120 / 120 (bez zmiany) | 120 / 120 | 120 / 120 |

- Zimny boot Ubuntu: **SSH dopiero po ~2 min** (cloud-init na każdym boocie
  klona bez datasource'u — do wyłączenia w golden: `cloud-init clean` +
  `/etc/cloud/cloud-init.disabled` przy provisioningu). Hit omija to całkowicie
  (restore 3.7 s, gotowość 0.6 s).
- Rozgrzewka działa: `ready.png` szablonu pokazuje w pełni załadowany App
  Center (Explore).
- Strona aplikacji nie otwierała się, bo driver robił `xdg-open snap://…`, a
  handlerem `x-scheme-handler/snap` na tym obrazie jest **`org.gnome.Software.desktop`**
  (gnome-software też jest zainstalowany). Sonda na żywo: `gio open snap://gimp`
  otwiera okno GNOME Software (25 % ekranu), **`snap-store snap://gimp` otwiera
  stronę GIMP-a w App Center** (9.6 % — strona w tym samym oknie; zrzuty
  aplikacji puste przez wygasły certyfikat appstream.ubuntu.com, jak 18.08).
  Driver zmieniony na `snap-store snap://<snap>`.

### Sygnał „okno sklepu istnieje" — co nie działa (2026-08-22)

| Pomysł | Wynik |
| --- | --- |
| `org.gnome.Shell.Introspect.GetWindows` (+ `gsettings set org.gnome.shell introspect true`) | GNOME Shell **50** (Fedora 44) i GNOME 46 (Ubuntu): `GDBus.Error.AccessDenied: GetWindows is not allowed` |
| eksport okien GTK na D-Bus (`gdbus introspect --dest org.gnome.Software --recurse` → `/org/gnome/Software/window/1`) | obiekt istnieje **także dla ukrytego** głównego okna usługi `--gapplication-service` — nie odróżnia „schowane" od „widoczne" |

Dlatego drivery zwracają `window_probe() = None` (mechanizm zostaje na KDE/
kolejne GNOME), a zabezpieczenia są dwa: (a) rozgrzewka szablonu czeka
`warmup_min_wait` = 60 s zanim `save` (raz na szablon), żeby stan objął
załadowany sklep; (b) settle aplikacji pozostaje klatkowe — dla pierwszej
aplikacji w zimnym biegu GNOME zwinięcie przeglądu Aktywności może zamknąć
settle po ~3 s (dystans ~1.0) zanim okno sklepu się pokaże; weryfikacja
szablonem (`verify`) pozostaje właściwym arbitrem. Po restore z rozgrzanym
szablonem sklep już jest na ekranie, więc każda aplikacja to nawigacja.

### Pełna matryca (3 dystrybucje × 2 aplikacje) — pierwsze podejście, skażone

`full-warm-hit` 520 s / `full-cold` 681 s — **nie są miarodajne**: Ubuntu
(4 × 120 s limitu przez `xdg-open`), WS kcalc (120 s przez fałszywe „no" z
sondy Introspect w pierwszej wersji), zimny KDE bez błędu dysku: 4.4 + 26.8 s.
Powtórka po poprawkach — niżej.

_(sekcja „Pełna matryca po poprawkach" — w trakcie)_

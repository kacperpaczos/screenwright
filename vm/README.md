# screenwright VM matrix

Automat do uruchamiania rzeczywistych software-centrów Linuksa w VMkach
libvirt, deployowania naszych screenshotów AppStream i sprawdzania, czy
sklep pokazuje to, co powinien.

Pełen plan i tło: `../docs/plans/6-vm-matrix.md`. Bieżący stan prac:
`../TODO.md` §6.

## Po co trzy maszyny

Testujemy, **czy dostarczanie screenshotów jest standardem, czy zależy od
sklepu**. Stąd taki, a nie inny dobór:

| Maszyna | Środowisko | Sklep | Rola w eksperymencie |
| --- | --- | --- | --- |
| `fedora-ws` | GNOME | GNOME Software | punkt odniesienia |
| `ubuntu-24.04` | GNOME | GNOME Software **+** snap-store | ten sam sklep, inna dystrybucja **oraz** inny sklep na tej samej maszynie |
| `fedora-kde` | Plasma | Discover | inny sklep, ta sama dystrybucja co punkt odniesienia |

Ubuntu dostaje oba sklepy celowo: dzięki temu różnica „GNOME Software vs
snap-store" jest mierzona przy **wszystkim innym takim samym**, a różnica
„GNOME Software na Fedorze vs na Ubuntu" — przy tym samym sklepie. Bez tego
nie da się rozdzielić wpływu sklepu od wpływu dystrybucji.

Uwaga: Ubuntu 24.04 **nie instaluje GNOME Software domyślnie** (zastąpione
przez App Center / snap-store), dlatego seed dokłada je jawnie.

## Wszystko bez roota

Cały tor — budowa obrazów, klony, przebieg matrycy, podgląd — chodzi na
`qemu:///session`:

- obrazy leżą w `~/.local/share/screenwright/images/` (`SCREENWRIGHT_IMAGE_ROOT`),
- sieć to usermode `passt`; gość nie ma adresu osiągalnego z hosta, więc SSH
  wchodzi przez **przekierowany port na 127.0.0.1** (runner nadaje każdej
  domenie wolny port, `vm/scripts/ubuntu-ssh.sh` wyciąga go z żywego XML-a),
- `/dev/kvm` jest dostępne dla wszystkich, `libguestfs` działa bez uprawnień.

Jedyne, co wymaga `sudo`, to instalacja paczek na hoście:

```bash
sudo dnf install virt-install virt-viewer guestfs-tools passt xorriso libosinfo
```

Nie trzeba włączać `libvirtd`, dopisywać się do grupy `libvirt` ani nic
konfigurować w `/etc/libvirt` — demon sesyjny startuje sam przy pierwszym
`virsh -c qemu:///session`.

## Struktura katalogów

```
~/.local/share/screenwright/images/      # SCREENWRIGHT_IMAGE_ROOT
  golden/                                # golden images (chmod 444)
    fedora-ws.qcow2
    fedora-kde.qcow2
    ubuntu-24.04.qcow2
    .cache-noble-server-cloudimg-amd64.img   # cache cloud image'a Ubuntu
  seed/
    ubuntu-24.04-seed.iso                # NoCloud seed użyty przy budowie
  build/                                 # katalogi robocze budowy (+ console.log)
  runs/                                  # overlaye zimnych klonów i zrzuty przebiegu (--work-root)
  warm/<distro>/                         # szablony warm cache (patrz niżej)

# Tu w repo:
vm/
  README.md                 # ten plik
  build/
    build-keypair.sh        # para kluczy SSH wstrzykiwana do wszystkich obrazów
    install-ssh-config.sh   # wpis Host screenwright-ubuntu w ~/.ssh/config
    install-fedora.sh       # Fedora WS / KDE: Anaconda + kickstart z distro_builders
    seed-ubuntu.sh          # Ubuntu: cloud image + NoCloud seed → pełny desktop
    run-matrix.sh           # wrapper na `python -m cli matrix --execute`
  scripts/
    ubuntu-ssh.sh           # SSH do domeny (port z <portForward> w dumpxml)
    diagnose-ubuntu.sh      # diagnostyka snap-store w gościu → JSON
    diagnose_ubuntu.py
```

XML domeny renderuje `domains/matrix/domain_xml.py` (szablon Jinja2 wpisany
w kod) — to jedyne źródło prawdy o konfiguracji maszyny.

## Tworzenie golden images

Każdy obraz to **pełna, normalna instalacja dystrybucji** z otwartym SSH,
autologinem użytkownika `test` i `qemu-guest-agent`. Nie cloud/server image —
te nie mają desktopu ani sklepu, więc `virsh screenshot` łapie na nich prompt
logowania.

Najpierw raz para kluczy — wszystkie instalatory ją wstrzykują:

```bash
vm/build/build-keypair.sh          # ~/.ssh/screenwright_ubuntu{,.pub}
```

Potem trzy budowy, **sekwencyjnie** (trzy naraz wyczerpały RAM hosta i OOM
killer ubił jedną w trakcie kompresji). Każda jest nienadzorowana i kończy
się sama; ~2 h łącznie.

```bash
# Fedora Workstation — GNOME + GNOME Software      (~30-60 min)
vm/build/install-fedora.sh ws

# Fedora KDE — Plasma + Discover                    (~30-60 min)
vm/build/install-fedora.sh kde

# Ubuntu 24.04 — GNOME + GNOME Software + snap-store (~20-40 min)
vm/build/seed-ubuntu.sh
```

Postęp widać w logu konsoli, którego ścieżkę skrypt wypisuje na starcie
(`tail -f ~/.local/share/screenwright/images/build/<wariant>.XXXXXX/console.log`).
Katalog roboczy jest kasowany tylko po sukcesie — po porażce zostaje razem
z obrazem w budowie.

Jak to działa:

- **Fedora** — Anaconda z kickstartem renderowanym przez `FedoraKdeBuilder` /
  `FedoraWsBuilder` (`virt-install --location --initrd-inject`). Kickstart
  kończy się `poweroff`, nie `reboot`: zgaszenie domeny jest sygnałem
  „instalacja skończona" dla `--wait -1`. Kickstarty są walidowane przez
  `pykickstart` w testach **i** w skrypcie przed startem instalacji — błąd
  składni wychodzi od razu, a nie po 40 minutach pobierania.
- **Ubuntu** — jednorazowy *provisioning boot* serwerowego cloud image'a z
  podpiętym NoCloud seed ISO. cloud-init instaluje `ubuntu-desktop`,
  `gnome-software` i `snap-store`, po czym gasi maszynę (`power_state`).
  Desktop jest **wypalony w golden image**; klony w matrycy startują gotowe.

Czego **nie** robić: podpinać seed ISO do klonów w przebiegu matrycy.
Overlay jest kasowany przy teardownie, więc cloud-init instalowałby cały
desktop od nowa przy każdym przebiegu.

Po budowie sprawdź maszynę ręcznie:

```bash
virsh -c qemu:///session list --all
python -m cli vm ssh <domena> -- snap list          # Ubuntu
python -m cli vm ssh <domena> -- systemctl status qemu-guest-agent
python -m cli vm snapshot <domena> /tmp/sprawdzam.png
```

## Pierwszy przebieg matrycy

Wymaga:
- golden image na miejscu (powyżej),
- `qemu-guest-agent` zainstalowany i uruchomiony w gościu (sprawdź
  `systemctl status qemu-guest-agent` przez SSH po pierwszym boocie),
- override screenshotów (`python -m cli override --help`) +
  serwer (`python -m cli serve start --directory poc/media`).

```bash
# Plan (suchy przebieg, tylko wypisuje kroki):
python -m cli matrix --spec matrix-spec.json

# Realny przebieg z virsh:
python -m cli matrix --spec matrix-spec.json --execute \
    --backend virsh --output vm/reports/matrix.json
```

Raport ląduje w `vm/reports/matrix.json` (struktura: `MatrixReport`
z `shared/results.py`), zrzuty i overlaye zimnych klonów w
`~/.local/share/screenwright/images/runs/` (`--work-root`; celowo nie `/tmp` —
na Fedorze to tmpfs i overlay zimnego klona potrafi go zapełnić w minutę).

`--execute` nie wystarczy: spec z `"dry_run": true` jest blokadą i CLI odmówi
(kod 2). Żeby bootować prawdziwe maszyny, spec musi mieć `dry_run: false`
(tak jest w `matrix-spec.json`) albo nie mieć tego klucza wcale.

Co robi runner per dystrybucja (`domains/matrix/runner.py` +
`domains/matrix/guest.py`):

1. overlay na golden → `virsh create` (domena transient),
2. czeka, aż `qemu-guest-agent` odpowiada, potem aż SSH do gościa działa
   (`ssh -p <port> test@127.0.0.1`, klucz `SCREENWRIGHT_SSH_KEY` /
   `~/.ssh/screenwright_ubuntu`), potem aż `graphical-session.target`
   użytkownika `test` (`DistroSpec.guest_user`) jest `active`,
3. komendy drivera sklepu odpala **przez SSH, w sesji użytkownika**:
   `systemd-run --user --collect --quiet [--wait] -- <komenda>` — proces ląduje
   w managerze użytkownika, gdzie GNOME/Plasma trzymają `DISPLAY`,
   `WAYLAND_DISPLAY` i szynę sesji. Agent **nie** nadaje się do tego: działa
   jako root w domenie SELinux `virt_qemu_ga_t`, która nie może ani zmienić
   użytkownika (`runuser`/`setpriv` → „Operation not permitted"), ani zagadać
   do systemd (`systemd-run` → „Access denied") — sprawdzone na Fedorze 44,
4. robi `virsh screenshot`, dopóki ekran nie **zmieni się względem klatki sprzed
   uruchomienia** i dwie kolejne klatki nie są identyczne (albo mija limit;
   zimny start GNOME Software potrafi rysować okno dopiero po ~45 s), i dopiero
   ten zrzut porównuje,
5. `virsh destroy` + usunięcie overlaya, także po błędzie.

Każda faza ląduje w raporcie jako `timings[]` (`PhaseTiming`), a CLI wypisuje
sumy per faza (`cli.matrix.timing_summary`).

## Warm cache (save / restore zamiast bootu)

Domyślnie włączony dla `--backend virsh` (`domains/matrix/warm_cache.py`).
Szablon per dystrybucja leży w `~/.local/share/screenwright/images/warm/<distro>/`:
`base.qcow2` (overlay po boocie, zamrożony), `state.save` (RAM z `virsh save`),
`domain.xml` (dokładny XML klona), `manifest.json`, `ready.png` (ekran w chwili
`save`). Każdy przebieg tworzy świeży `disk.qcow2` z backing `base.qcow2` pod tą
samą ścieżką i robi `virsh restore --xml domain.xml state.save`; domena nazywa
się `sw-<distro>-warm`, bo restore wymaga tej samej nazwy co save.

- **chybienie** (brak szablonu, zmieniony golden / sprzęt klona / wersja QEMU,
  zajęty port SSH): zimny boot do gotowości → `save` → zamrożenie → `restore`,
  czyli pierwszy przebieg przechodzi tę samą ścieżką, co każdy następny;
- **nieudany restore**: ostrzeżenie w logu (`matrix.warm.restore_failed`),
  szablon skasowany, zimny boot — nigdy cicho;
- drugi przebieg tej samej dystrybucji w tym samym czasie dostaje
  `matrix.warm.busy` i bootuje po staremu (flock na katalogu szablonu).

Flagi: `--no-warm-cache` (zawsze zimno), `--warm-root DIR`,
`--rebuild-warm-cache` (skasuj szablony dystrybucji ze specu). `--backend fake`
nie używa warm cache, chyba że podasz `--warm-root`.

Plik stanu ma rozmiar RAM-u gościa; w trybie sesji demon czyta
`~/.config/libvirt/qemu.conf` (bez sudo) — `save_image_format = "zstd"` daje
~1 GB przy 4 GiB gościa. Po `dnf upgrade` QEMU szablony są unieważniane
automatycznie (manifest trzyma wersję hypervisora). Liczby: `../docs/matrix-timing.md`.

## Zdalny podgląd (human in the loop)

```bash
python -m cli vm view <vm-name>              # virt-viewer na qemu:///session
virt-viewer -c qemu:///session <vm-name>     # to samo wprost
```

Podgląd działa równolegle z matrycą — można podpiąć się w trakcie i
odetchnąć bez wpływu na wynik.

## Znane ograniczenia (TODO §6)

- **Cloud/server image ≠ image do testów sklepu.** `Fedora Cloud Edition`
  i `noble-server-cloudimg` nie mają ani Discover, ani snap-store — VM
  wstaje na konsolę tekstową i `virsh screenshot` łapie prompt logowania.
  Golden musi być pełną instalacją desktopu (patrz wyżej).
- **Seed ISO musi być podpięte do domeny**, nie tylko do `virt-customize`.
  Ścieżka idzie przez `DistroSpec.seed_iso` → `render_domain_xml(cdrom_path=…)`
  — używana tylko przy budowie, nigdy dla klonów.
- `plasma-discover --application` działa na Discover 6.7+; starsze wersje
  wymagają D-Bus (niezweryfikowane).
- Drivery mintinstall/AppCenter są puste do czasu TODO §3 (decyzja które
  sklepy testujemy dla każdej dystrybucji). Ubuntu ma driver snap-store,
  ale sama **podmiana** screenshotów przez snap-store-proxy nie ma
  zweryfikowanej ścieżki wpięcia — patrz `../docs/snap-store-diagnostics.md`.
- Zegar gościa rozjeżdża się po `virsh restore`. Dla screenshotów bez
  znaczenia.

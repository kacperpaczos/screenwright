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
  scripts/
    ubuntu-ssh.sh           # SSH do domeny (port z <portForward> w dumpxml)
    diagnose-ubuntu.sh      # diagnostyka snap-store w gościu → JSON
    diagnose_ubuntu.py
```

> **Uwaga (2026-08-22):** silnik uruchamiania matrycy (runner, warm cache,
> drivery, renderowanie XML domeny) został wycofany — provisioning i uruchamianie
> robi teraz Ansible (`ansible/`). Ten plik opisuje już tylko **budowę golden
> images**, które nadal służą do weryfikacji wizualnej cel 2. Historia matrycy:
> `docs/matrix-timing.md`; sekwencja retirementu: `BACKLOG.md`.

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

## Uruchamianie i weryfikacja — przeniesione do Ansible

Silnik uruchamiania matrycy (`cli matrix`, runner, warm cache save/restore,
drivery sklepów, snap-store-proxy) został **wycofany 2026-08-22**. Zbieranie
katalogów (cel 1) i podmianę + weryfikację zrzutów (cel 2) robi teraz Ansible:

```bash
cd ansible && ansible-playbook playbooks/site.yml            # provision → collect (cel 1)
ansible-playbook playbooks/deploy-override.yml \            # podmiana + weryfikacja (cel 2)
    -e override_component_id=GameConqueror.desktop -e override_prefix=gimp
```

Golden images (budowane powyżej) nadal służą do weryfikacji wizualnej cel 2
(overlay → boot → override → `virsh screenshot` → porównanie). Prymitywy VM
(`domains/matrix/backend`, `guest.py`) zostają do czasu, aż weryfikacja stanie
się repo-toolem `visual-check`. Pomiary bootu i warm-cache z Etapu 0:
`docs/matrix-timing.md`. Pełna sekwencja retirementu: `BACKLOG.md`.

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
- `plasma-discover --application` działa na Discover 6.7+; starsze wersje
  wymagają D-Bus (niezweryfikowane).
- Sama **podmiana** screenshotów w snapie nie ma ścieżki przez AppStream
  (snap omija katalog) — patrz `../docs/snap-store-diagnostics.md` i
  `../docs/platform-notes.md`. Podmiana rpm/deb działa (patch katalogu
  bazowego, `../docs/override-deploy.md`).

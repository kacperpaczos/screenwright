# screenwright VM matrix

Automat do uruchamiania rzeczywistych software-centrów Linuksa w VMkach
libvirt, deployowania naszych screenshotów AppStream i sprawdzania, czy
sklep pokazuje to, co powinien.

Pełen plan i tło: `../docs/plans/6-vm-matrix.md`.

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

## Stan

- **M0 — host prep: zrobione.** Paczki (`@virtualization`, `virt-install`,
  `virt-viewer`, `guestfs-tools`), `libvirtd`, struktura katalogów.
- **M1 — golden images: skrypty gotowe, obrazy do zbudowania.** Wcześniejsze
  przebiegi używały obrazów Cloud/server (bez desktopu, bez sklepu) i
  `FakeBackend` — patrz `../docs/snap-store-diagnostics.md`.

## Wymagania hosta

```bash
sudo dnf install @virtualization virt-install virt-viewer guestfs-tools
sudo systemctl enable --now libvirtd
# Jednorazowo:
sudo usermod -aG libvirt $USER   # potem nowe logowanie
```

## Struktura katalogów

```
/var/lib/libvirt/images/
  golden/                    # golden images (read-only, chmod 444)
    fedora-kde-44.qcow2
    fedora-ws-44.qcow2
    ...
  state/                     # virsh save state files (per golden)
    fedora-kde-44.qcow2.save.zst

# Tu w repo:
vm/
  README.md                  # ten plik
  templates/
    domain.xml.j2            # kanoniczny szablon domeny
  build/
    fedora-kde-44.ks         # kickstart dla nowego golden image
    seed-golden.sh           # weź cloud image → golden (autologin, agenty)
    run-matrix.sh            # wrapper na `python -m cli matrix --execute`
```

## Tworzenie golden images

Każdy obraz to **pełna, normalna instalacja dystrybucji** z otwartym SSH,
autologinem i `qemu-guest-agent`. Nie cloud/server image — te nie mają
desktopu ani sklepu, więc `virsh screenshot` łapie na nich prompt logowania.

Najpierw raz, bez `sudo`, para kluczy — wszystkie instalatory ją wstrzykują:

```bash
vm/build/build-keypair.sh          # ~/.ssh/screenwright_ubuntu{,.pub}
```

Potem trzy budowy. Każda jest nienadzorowana i kończy się sama; nie wymagają
siebie nawzajem, więc można je odpalać w dowolnej kolejności.

```bash
# Fedora Workstation — GNOME + GNOME Software      (~30-60 min)
sudo vm/build/install-fedora.sh ws

# Fedora KDE — Plasma + Discover                    (~30-60 min)
sudo vm/build/install-fedora.sh kde

# Ubuntu 24.04 — GNOME + GNOME Software + snap-store (~20-40 min)
sudo vm/build/seed-ubuntu.sh
```

Postęp widać w logu konsoli, którego ścieżkę skrypt wypisuje na starcie
(`tail -f /tmp/screenwright-*/console.log`).

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
virsh -c qemu:///system list --all
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
z `shared/results.py`).

## Save / restore (cross-run warm cache)

Po pełnym boocie i pierwszej konfiguracji golden image'a warto zapisać
RAM do pliku — kolejne matryce startują w 1 s zamiast 30 s:

```bash
virsh save <vm-name> /var/lib/libvirt/images/state/fedora-kde-44.qcow2.save.zst
```

W pliku konfiguracyjnym libvirtd ustaw `save_image_format = "zstd"` —
pliki stanu mają rozmiar RAM-u (~960 MB dla 2 GB gościa).

Po `dnf upgrade` na hoście save file jest nieaktualny. Usuń go i
pozwól, by następny przebieg wykonał cold boot.

## Zdalny podgląd (human in the loop)

```bash
virt-viewer -c qemu:///system <vm-name>     # VNC
remote-viewer $(virsh domdisplay <vm-name>)
```

Podgląd działa równolegle z matrycą — można podpiąć się w trakcie i
odetchnąć bez wpływu na wynik.

## Znane ograniczenia (TODO §6)

- **Cloud/server image ≠ image do testów sklepu.** `Fedora Cloud Edition`
  i `noble-server-cloudimg` nie mają ani Discover, ani snap-store — VM
  wstaje na konsolę tekstową i `virsh screenshot` łapie prompt logowania.
  Golden musi być spinem desktopowym (KDE) albo cloud image'em z doinstalowanym
  desktopem przez NoCloud seed (patrz `seed-ubuntu.sh`).
- **Seed ISO musi być podpięte do domeny**, nie tylko do `virt-customize`.
  Ścieżka idzie przez `DistroSpec.seed_iso` → `render_domain_xml(cdrom_path=…)`.
- `plasma-discover --application` działa na Discover 6.7+; starsze wersje
  wymagają D-Bus (niezweryfikowane).
- Drivery mintinstall/AppCenter są puste do czasu TODO §3 (decyzja które
  sklepy testujemy dla każdej dystrybucji). Ubuntu ma driver snap-store,
  ale sama **podmiana** screenshotów przez snap-store-proxy nie ma
  zweryfikowanej ścieżki wpięcia — patrz `docs/snap-store-diagnostics.md`.
- Zegar gościa rozjeżdża się po `virsh restore` (brak RTC w cloud
  image'ach). Dla screenshotów bez znaczenia.
# screenwright VM matrix

Automat do uruchamiania rzeczywistych software-centrów Linuksa w VMkach
libvirt, deployowania naszych screenshotów AppStream i sprawdzania, czy
sklep pokazuje to, co powinien.

Pełen plan i tło: `../docs/plans/6-vm-matrix.md`.

## Stan

- **M0 — host prep: zrobione.** Paczki (`@virtualization`, `virt-install`,
  `virt-viewer`, `guestfs-tools`), `libvirtd`, struktura katalogów.
- **M1 — proof on one distro: w trakcie.** Jeden golden image (Fedora KDE),
  jeden realny przebieg matrycy z `--backend virsh`.

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

## Tworzenie golden image (M1)

Najszybsza ścieżka: weź oficjalny cloud image Fedory 44 KDE i dolej
post-install przez `seed-golden.sh`:

```bash
# Fedora 44 KDE cloud image (Base + KDE Spin)
curl -L -o /var/lib/libvirt/images/golden/fedora-kde-44.qcow2 \
    https://download.fedoraproject.org/pub/fedora/linux/releases/44/KDE/x86_64/images/Fedora-KDE-44-1.6.x86_64.qcow2

# Przygotuj (instaluje agenty, włącza autologin, czyści cache, sparsifikuje).
sudo vm/build/seed-golden.sh /var/lib/libvirt/images/golden/fedora-kde-44.qcow2

# Zamknij na cztery spusty:
sudo chmod 444 /var/lib/libvirt/images/golden/fedora-kde-44.qcow2
```

Dla M2+ budujemy od zera kickstartem
(`vm/build/fedora-kde-44.ks` → `virt-install --initrd-inject`). Wtedy nie
zależymy od cloud image'u i możemy zdecydować o wszystkim (rozmiary
partycji, paczki, lokalizacja, sieć).

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

- `plasma-discover --application` działa na Discover 6.7+; starsze wersje
  wymagają D-Bus (niezweryfikowane).
- Drivery mintinstall/AppCenter/Ubuntu są puste do czasu TODO §3
  (decyzja które sklepy testujemy dla każdej dystrybucji).
- Zegar gościa rozjeżdża się po `virsh restore` (brak RTC w cloud
  image'ach). Dla screenshotów bez znaczenia.
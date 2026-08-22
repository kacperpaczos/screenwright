# Platform notes — twarde fakty o hoście, VM-ach i sklepach

Skonsolidowana wiedza „która kosztowała czas", zebrana przy budowie kolektorów
(cel 1) i podmiany zrzutów (cel 2). Każda pozycja to pułapka albo nieoczywista
decyzja, którą łatwo odkryć na nowo od zera. Szczegóły pomiarowe: linki na końcu.

Host odniesienia: Fedora, libvirt 12, QEMU 10.2, passt 2026-07, 8 rdzeni / 30 GiB,
`/home` btrfs. Golden images: `~/.local/share/screenwright/images/golden/`.

## libvirt / QEMU

- **`qemu:///session` (rootless), nie `qemu:///system`.** Cała praca leci w sesji
  użytkownika: pule i dyski w `~/.local/share/...`, brak sudo, brak kolizji z
  systemowym demonem. Ceną jest sieć (patrz passt).
- **Terraform `dmacvicar/libvirt` jest niezdatny w tym trybie.** Provider łączy się
  z `qemu:///system` **mimo** `uri="qemu:///session"` / `LIBVIRT_DEFAULT_URI` →
  domeny lądują w systemowym demonie, a qemu (uid 107) nie czyta puli w `HOME`
  (`Permission denied (as uid:107)`). Dlatego prowizja idzie **Ansible +
  `virt-install`**, nie Terraform. Diagnoza zaparkowana w `terraform/README.md` /
  `BACKLOG.md`.
- **Domena z `virt-install` bez `--transient` jest PERSISTENT.** `virsh destroy`
  ją tylko gasi (zostaje `shut off`), więc kolejny `virt-install --name X` pada na
  „name already in use". Sprzątać ZAWSZE `destroy` **+** `undefine`. (Kosztowało
  cały cichy przebieg harnessu — `wait_for_agent` odpytywał martwą domenę.)
- **`virsh send-key <dom> --codeset linux KEY_ESC`** wstrzykuje zdarzenie klawisza
  na warstwie wejścia QEMU — działa bez żadnego narzędzia w gościu i bez fokusu.
  Jedyny pewny sposób na zdjęcie modala GNOME, bo `org.gnome.Shell.Eval` jest
  domyślnie wyłączony (zwraca „Usage:").
- **`virsh screenshot`** (framebuffer VNC) to jedyny pewny zrzut ekranu: nie zależy
  od sesji ani narzędzi gościa. `gnome-screenshot` przez `systemd-run --user`
  **wiesza się** (rc=124), a `grim` **nie działa na GNOME/Mutter** (wymaga
  `wlr-screencopy` — protokołu wlroots). `grim` miałby sens tylko pod headless
  kompozytorem wlroots (`cage`/`sway --headless`), ale to już nie jest GNOME.

## Sieć gości

- **passt (usermode, bezrootowy), nie NAT `default`.** Na tej stacji systemowy NAT
  nie forwarduje egressu z gości bez zmiany firewalld wymagającej roota
  (`ping 8.8.8.8` = 100% loss). passt działa w sesji; SSH przez port-forward:
  `--network user,backend.type=passt,portForward0.proto=tcp,portForward0.address=127.0.0.1,portForward0.range0.start=<PORT>,portForward0.range0.to=22`.
- **IPv4-only w gościu, bo mirrory mają AAAA i `dnf`/`apt` wiszą na IPv6.** cloud-init
  wyłącza IPv6 + `dnf` `ip_resolve=4` + `apt` `ForceIPv4`. Bez tego provisioning
  potrafi zawisnąć na pobraniu pakietów.

## Sesja i procesy w gościu

- **`qemu-guest-agent` jest SELinux-confined (`virt_qemu_ga_t`)** — `guest-exec`
  biega jako root **bez** sesji graficznej i nie wejdzie do sesji użytkownika. Do
  GUI i sesji: **SSH** + `systemd-run --user` (importuje `WAYLAND_DISPLAY`/`DISPLAY`
  ze zbootowanej sesji GNOME; potwierdzone: `systemctl --user show-environment`
  pokazuje `WAYLAND_DISPLAY=wayland-0`, `DISPLAY=:0`).
- **Procesy w tle przez SSH giną z zamknięciem kanału** (`nohup`/`setsid &` nie
  wystarcza dla serwera, który ma przeżyć). Trwały proces w gościu = **jednostka
  systemd**: `systemd-run --unit=<nazwa> --collect -- <cmd>`. (Serwer mediów do
  cel 2 działa dopiero jako `swmedia`.)
- **`systemd-oomd` na hoście ubija cały scope terminala**, gdy budowy obrazów
  nakładają się na klony VM. Długie budowy izolować w `systemd-run --user --unit`
  i pollować plik statusu (patrz `docs/collectors.md`).

## AppStream i sklepy (cel 2 — podmiana zrzutów)

Najważniejsze, bo nieoczywiste i kosztowne:

- **libappstream UNIONuje listy `<screenshots>`** komponentów o tym samym `<id>`
  z różnych katalogów. Osobny plik override z `priority=1` tylko **dodaje** nasz
  zrzut obok oryginału (dump = 2 zrzuty, sklep renderuje bazowy pierwszy).
- **`merge="replace"` jest po cichu ignorowany** przez `appstreamcli refresh`/pool
  (także z `version="0.8"`, `type="desktop"`) — wynik: tylko bazowy zrzut.
- **Jedyne, co daje „tylko nasz": przepisanie `<screenshots>` w SAMYM katalogu
  bazowym** (`/usr/share/swcatalog/xml/fedora.xml.gz`) i zapis całego katalogu.
  Implementacja: `domains/override.patch_catalog` / `cli override --patch`.
- Katalog Fedory jest **zwykłym XML bez namespace** (`<components origin="fedora"
  version="0.8">`, `<component type="desktop">`); appstream-generator produkuje
  wariant z domyślnym `xmlns="http://appstream.org/"`. Kod obsługuje oba.
- Metadane, które **faktycznie** czyta sklep, to skompilowany `.xb`:
  `/var/cache/swcatalog/cache/en-US-os-catalog.xb` (gnome-software go mmapuje).
  `appstreamcli dump <id>` = ta sama rozdzielczość co widzi sklep — dobre do asercji.
- **GNOME Software 50 — pułapki karuzeli:**
  - **pojedyncza instancja**: `--details=<id>` do działającego procesu pokazuje
    STARY cache. Sekwencja: `gnome-software --quit` + `pkill -9` **przed**
    `rm -rf ~/.cache/gnome-software ~/.local/share/gnome-software`, dopiero potem
    `systemd-run --user gnome-software --details=<id>`.
  - **re-enkoduje** pobrane zrzuty do cache → sha pliku w
    `~/.cache/gnome-software/screenshots/*` ≠ sha oryginału; do rozpoznania „nasz
    vs bazowy" porównywać **średni kolor** (`convert … -resize 1x1 txt:-`), nie sha.
  - modal „Enable Third Party" zasłania karuzelę → zdejmowany `virsh send-key … KEY_ESC`.
  - dla aplikacji dostępnej i jako rpm, i jako flatpak, sklep może pokazać wariant
    flatpaka (Flathub, poza katalogiem rpm) → patch celuje w komponent rpm.
- **snap omija AppStream** — snapd ma własne REST (`/v2/find`), zrzuty z
  `dashboard.snapcraft.io`. Podmiana zrzutu snapa jest poza zasięgiem patcha
  katalogu (patrz `docs/snap-store-diagnostics.md`).

Wniosek protokołowy: skuteczna podmiana jest **per platforma/wariant** (rpm, deb,
flatpak, snap), którą sklep wyświetla — nie globalnie i nie per-sklep. Ponieważ
GNOME Software i KDE Discover czytają ten sam katalog przez libappstream, patch
katalogu działa dla obu (warstwa danych wspólna).

## Gdzie szukać liczb i szczegółów

- `docs/collectors.md` — jak stawiać/uruchamiać kolektory, pokrycie (cel 1).
- `docs/override-deploy.md` — pełny obieg cel 2 + 3-warstwowy dowód wizualny.
- `docs/screenshot-protocol.md`, `docs/store-screenshot-delivery.md` — protokół
  dostarczania zrzutów per platforma.
- `docs/snap-store-diagnostics.md` — dlaczego snap nie przez AppStream.
- `docs/matrix-timing.md` — pomiary boot/warm-cache z Etapu 0 (stary tor matrycy).
- `BACKLOG.md`, `terraform/README.md` — diagnoza Terraform, otwarte zadania.

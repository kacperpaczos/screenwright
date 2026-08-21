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

_(sekcje „Pomiar bazowy" i „Warm cache" — uzupełniane w miarę wyników)_

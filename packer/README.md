# Packer — deklaratywne golden images

Zastępuje ręczne buildery (`vm/build/install-fedora.sh`, `seed-ubuntu.sh` +
`domains/matrix/distro_builders/`) deklaratywnym Packerem. Cel: móc odtworzyć
golden images jedną komendą i odblokować retirement builderów (patrz `BACKLOG.md`).

Wymaga: `packer` (v1.16+) + plugin qemu (`packer plugins install github.com/hashicorp/qemu`),
`qemu-system-x86_64`, `/dev/kvm` (0666, bez roota). Klucz SSH: `vm/build/build-keypair.sh`.

## Dlaczego Packer, nie libvirt/Terraform

Packer uruchamia qemu **wprost**, z siecią user-mode (SLIRP) — ma egress bez roota
i bez passt, więc omija problem NAT-u `qemu:///system` z tej stacji (ten sam, który
zablokował Terraform, patrz `terraform/README.md`). `/dev/kvm` daje akcelerację.

## Ubuntu 24.04 (`ubuntu.pkr.hcl`) — ZWERYFIKOWANE (build), smoke: TODO

Model = deklaratywny odpowiednik `seed-ubuntu.sh`: cloud image jako dysk bazowy +
NoCloud `cidata` CD (user-data z `UbuntuBuilder`) → cloud-init instaluje
`ubuntu-desktop` + `gnome-software` + `snap-store` + `qemu-guest-agent`, ustawia
autologin `test`, i **sam gasi maszynę** (`power_state: poweroff`). Packer z
`communicator = "none"` czeka na to zgaszenie.

```bash
packer plugins install github.com/hashicorp/qemu   # raz
packer/build-ubuntu.sh                              # ~15 min; obraz → packer/build/ubuntu-out/
```

**Pułapka (kosztowała jeden build):** qemu Packera domyślnie NIE ma kanału
`org.qemu.guest_agent.0`. Bez niego postinst `qemu-guest-agent` pada i cloud-init
przerywa CAŁĄ instalację przed konfiguracją SSH/usera — a Packer i tak kończy się
„sukcesem", bo VM się zgasił (po porażce). Dlatego:
1. `qemuargs` dokłada kanał virtio-serial guest-agent (jak robi virt-install);
2. `build-ubuntu.sh` sprawdza w logu konsoli marker `screenwright cloud-init done`
   (ostatni krok cloud-init) i przy jego braku zwraca **RESULT=INCOMPLETE** —
   samo `PACKER_RC=0` nie wystarcza.

Objaw kompletności: build trwa ~15 min (pełna instalacja), nie ~6 min (przerwany).

## Fedora WS / KDE (`fedora.pkr.hcl`) — NAPISANE, NIEZWERYFIKOWANE (build jutro)

Fedora Cloud Base jako dysk bazowy + `cidata` CD z cloud-init, który `dnf`-instaluje
grupę pulpitu (`@^workstation-product-environment` / `@^kde-desktop-environment`) +
sklep (`gnome-software` / `plasma-discover`) + `qemu-guest-agent`, tworzy usera
`test` z kluczem i autologinem, i gasi maszynę. Uniform z Ubuntu (bez `boot_command`
Anacondy, który wymaga strojenia na żywym boocie). Alternatywa (proven, ale
złożona w Packerze): Anaconda + kickstart z `FedoraWsBuilder`/`FedoraKdeBuilder`
— patrz `vm/build/install-fedora.sh`.

```bash
packer/build-fedora.sh ws     # lub: kde   (build jutro; jeden VM naraz!)
```

## Zasada bezpieczeństwa hosta (twarda)

Stacja ma ~14 GiB wolnego RAM (30 GiB − ~16 GiB desktopu). **Tylko JEDEN VM naraz.**
Nigdy nie odpalać smoke-testu, gdy build jeszcze kończy, ani dwóch buildów, ani
buildu + `cli visualcheck` równocześnie — `systemd-oomd` ubija wtedy cały scope
sesji (raz zabił też shell). Buildy są w izolowanym `systemd-run --user`; smoke/
verify też muszą być. Patrz notatka `project-host-memory-oomd`.

## Promocja do golden (ręczna, po smoke-teście)

Build NIE nadpisuje działającego golden. Po `RESULT=OK` i pozytywnym smoke
(boot → SSH → `gnome-software`/`snap-store`/`plasma-discover` obecne):

```bash
mv packer/build/ubuntu-out/ubuntu-24.04.qcow2 \
   ~/.local/share/screenwright/images/golden/ubuntu-24.04.qcow2
```

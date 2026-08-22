"""Builder Ubuntu 24.04 — automatyczna instalacja desktopu (cloud-init NoCloud).

Renderuje parę plików (user-data + meta-data) dla NoCloud seed ISO. Klucz
SSH hosta wstrzykiwany jest do user-data jako ``ssh_authorized_keys`` dla
użytkownika ``test``, co pozwala runnerowi SSH-ować do VM bez hasła.

Ten seed jest **artefaktem budowy, nie runtime'u**. ``packer/build-ubuntu.sh``
robi jednorazowy provisioning boot serwerowego cloud image'a z podpiętym seedem:

    noble-server-cloudimg-amd64.img
        → boot z seed.iso → cloud-init instaluje ubuntu-desktop + snap-store
        → power_state: poweroff → sparsify → golden-24.04.qcow2

Efektem jest golden image z **już zainstalowanym** desktopem. Klony w matrycy
startują gotowe i nie widzą seeda w ogóle.

Nie wolno podpinać tego seeda do klonów w przebiegu matrycy: overlay jest
kasowany przy teardownie, więc cloud-init instalowałby cały desktop od nowa
przy **każdym** przebiegu (kilkanaście minut na app). ``DistroSpec.seed_iso``
istnieje dla provisioningu i wyjątków, nie dla ścieżki produkcyjnej.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from domains.matrix.distro_builders._ssh import load_pubkey, resolve_pubkey_path
from domains.matrix.models import DistroName

if TYPE_CHECKING:
    from pathlib import Path

_USER_DATA_TEMPLATE = """#cloud-config
locale: en_US.UTF-8
timezone: Europe/Warsaw
package_update: true
package_upgrade: false
# Instalacja musi przejść bez ani jednego pytania — provisioning leci
# bez konsoli, więc każdy debconf-prompt zawiesiłby build na zawsze.
apt:
  conf: |
    APT::Get::Assume-Yes "true";
    APT::Get::Fix-Broken "true";
    DPkg::Options { "--force-confdef"; "--force-confold"; };
packages:
  # Pełny ubuntu-desktop, nie -minimal: chcemy dokładnie tego GNOME-a,
  # którego dostaje użytkownik.
  - ubuntu-desktop
  # Ubuntu 24.04 domyślnie daje App Center (snap-store) i NIE instaluje
  # GNOME Software. Dokładamy je jawnie — bez tego nie da się porównać
  # „GNOME Software na Ubuntu" z „GNOME Software na Fedorze".
  - gnome-software
  - gnome-software-plugin-deb
  - qemu-guest-agent
  - openssh-server
  - xdg-utils
snap:
  commands:
    - [install, snap-store]
users:
  - name: test
    gecos: "Test User"
    groups: [adm, sudo]
    shell: /bin/bash
    sudo: ALL=(ALL) NOPASSWD:ALL
    lock_passwd: false
    passwd: "$6$rounds=4096$screenwright$screenwright"
    ssh_authorized_keys:
      - {{ ssh_pubkey | e }}
hostname: screenwright
ssh_pwauth: true
runcmd:
  - [systemctl, enable, --now, qemu-guest-agent]
  - [bash, -c, "echo 'test ALL=(ALL) NOPASSWD:ALL' > /etc/sudoers.d/90-test-nopasswd && chmod 0440 /etc/sudoers.d/90-test-nopasswd"]
  # Autologin: bez zalogowanej sesji graficznej nie ma czego zrzucić
  # przez `virsh screenshot` — sklep nie ma się gdzie narysować.
  - [bash, -c, "printf '[daemon]\\nAutomaticLoginEnable=true\\nAutomaticLogin=test\\n' > /etc/gdm3/custom.conf"]
  - [systemctl, set-default, graphical.target]
  # Wygaszacz/blank psuje deterministyczne zrzuty.
  - [bash, -c, "sudo -u test gsettings set org.gnome.desktop.session idle-delay 0 || true"]
  - [bash, -c, "sudo -u test gsettings set org.gnome.desktop.screensaver lock-enabled false || true"]
  # Chrom pierwszego uruchomienia zasłania okno sklepu na każdym zrzucie.
  # Kreator „Welcome to Ubuntu" (gnome-initial-setup):
  - [bash, -c, "install -d -o test -g test /home/test/.config && install -o test -g test /dev/null /home/test/.config/gnome-initial-setup-done"]
  - [bash, -c, "rm -f /etc/xdg/autostart/gnome-initial-setup-first-login.desktop /etc/xdg/autostart/gnome-initial-setup-copy-worker.desktop"]
  # Modal „Software Updater" i powiadomienia update-notifiera:
  - [bash, -c, "rm -f /etc/xdg/autostart/update-notifier.desktop"]
  - [bash, -c, "printf 'APT::Periodic::Update-Package-Lists \\"0\\";\\nAPT::Periodic::Unattended-Upgrade \\"0\\";\\nAPT::Periodic::Download-Upgradeable-Packages \\"0\\";\\n' > /etc/apt/apt.conf.d/99screenwright-no-auto"]
  - [bash, -c, "systemctl disable --now unattended-upgrades.service apt-daily.timer apt-daily-upgrade.timer || true"]
  # Zgłoszenia awarii (apport) też potrafią wyskoczyć na wierzch.
  - [bash, -c, "systemctl disable --now apport.service || true"]
  # Zwolnione bloki oddane hostowi — bez tego golden image zostaje rozdmuchany
  # do pełnego rozmiaru dysku niezależnie od tego, ile realnie zajmuje system.
  - [bash, -c, "apt-get clean && fstrim -av || true"]
final_message: "screenwright cloud-init done after $UPTIME seconds"
# Provisioning kończy się samo-wyłączeniem: `virt-install --wait -1` wraca,
# gdy domena zgaśnie, więc to jest sygnał „instalacja skończona".
# Klony golden image'a tego NIE wykonają — mają już zapisany stan cloud-inita
# dla tego instance-id i nie dostają seed ISO, więc moduły się nie powtarzają.
power_state:
  mode: poweroff
  timeout: 30
  condition: true
"""

_META_DATA = "instance-id: screenwright-ubuntu-24.04\nlocal-hostname: screenwright\n"


class UbuntuBuilder:
    """Renderuje NoCloud seed dla Ubuntu 24.04 desktop."""

    name = DistroName.UBUNTU

    def __init__(self, ssh_pubkey_path: Path | None = None) -> None:
        self._ssh_pubkey_path = resolve_pubkey_path(ssh_pubkey_path)

    def render_installer(self, out_dir: Path) -> Path:
        out_dir.mkdir(parents=True, exist_ok=True)
        user_data = out_dir / "user-data"
        meta_data = out_dir / "meta-data"
        user_data.write_text(self._render_user_data(), encoding="utf-8")
        meta_data.write_text(_META_DATA, encoding="utf-8")
        return out_dir

    def golden_path(self, images_dir: Path) -> Path:
        return images_dir / "golden" / "ubuntu-24.04.qcow2"

    def _render_user_data(self) -> str:
        from jinja2 import Environment, StrictUndefined

        env = Environment(undefined=StrictUndefined)
        return env.from_string(_USER_DATA_TEMPLATE).render(
            ssh_pubkey=load_pubkey(self._ssh_pubkey_path)
        )


__all__ = ["UbuntuBuilder"]

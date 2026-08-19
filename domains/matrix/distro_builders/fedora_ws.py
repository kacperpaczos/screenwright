"""Builder Fedora Workstation — Kickstart z @^workstation-product-environment.

Pełna, nienadzorowana instalacja przez ``virt-install --initrd-inject``
(patrz ``vm/build/install-fedora.sh``). Efekt: GNOME + GNOME Software,
autologin użytkownika ``test``, otwarty SSH z kluczem hosta, qemu-guest-agent.

To jest druga połowa eksperymentu „czy GNOME Software serwuje screenshoty
tak samo wszędzie": ten sam sklep co na Ubuntu, ale katalog i pakowanie
Fedory. Różnice między tą maszyną a Ubuntu obciążają dystrybucję, a nie sklep.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from domains.matrix.distro_builders._ssh import load_pubkey, resolve_pubkey_path
from domains.matrix.models import DistroName

if TYPE_CHECKING:
    from pathlib import Path


class FedoraWsBuilder:
    name = DistroName.FEDORA_WS

    def __init__(self, ssh_pubkey_path: Path | None = None) -> None:
        self._ssh_pubkey_path = resolve_pubkey_path(ssh_pubkey_path)

    def render_installer(self, out_dir: Path) -> Path:
        target = out_dir / "fedora-ws.ks"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(self._render(), encoding="utf-8")
        return target

    def golden_path(self, images_dir: Path) -> Path:
        return images_dir / "golden" / "fedora-ws.qcow2"

    def _render(self) -> str:
        from jinja2 import Environment, StrictUndefined

        env = Environment(undefined=StrictUndefined)
        return env.from_string(_KICKSTART).render(ssh_pubkey=load_pubkey(self._ssh_pubkey_path))


_KICKSTART = """# Fedora Workstation 44 — nienadzorowana instalacja (virt-install --initrd-inject)
url --mirrorlist=https://mirrors.fedoraproject.org/mirrorlist?repo=fedora-44&arch=x86_64
lang en_US.UTF-8
keyboard us
timezone UTC --utc
bootloader --location=mbr
clearpart --all --initlabel
autopart --type=lvm
network --bootproto=dhcp --device=link --activate --hostname=screenwright-fedora-ws
rootpw --lock
user --name=test --password=test --plaintext --gecos="screenwright test" --groups=wheel
{% if ssh_pubkey %}sshkey --username=test "{{ ssh_pubkey }}"
{% endif %}# SSH musi być otwarty: cała diagnostyka i deploy override'ów idzie po nim.
firewall --enabled --service=ssh
services --enabled=sshd,qemu-guest-agent
selinux --enforcing

%packages
@^workstation-product-environment
gnome-software
qemu-guest-agent
spice-vdagent
openssh-server
%end

%post --log=/var/log/screenwright-post.log
# Bezhasłowe sudo — diagnostyka i deploy override'ów idą po SSH bez terminala,
# więc zwykłe `wheel` z pytaniem o hasło je blokuje.
echo 'test ALL=(ALL) NOPASSWD:ALL' > /etc/sudoers.d/90-test-nopasswd
chmod 0440 /etc/sudoers.d/90-test-nopasswd

# Autologin — bez zalogowanej sesji `virsh screenshot` łapie ekran logowania.
mkdir -p /etc/gdm
cat > /etc/gdm/custom.conf <<'EOF'
[daemon]
AutomaticLoginEnable=True
AutomaticLogin=test
EOF

systemctl set-default graphical.target
# gnome-initial-setup przykryłby sklep oknem powitalnym.
systemctl disable initial-setup.service initial-setup-reconfiguration.service || true
mkdir -p /home/test/.config
touch /home/test/.config/gnome-initial-setup-done
chown -R test:test /home/test/.config

# gnome-tour to OSOBNE okno od initial-setup — modal „Welcome to Fedora Linux"
# ląduje na wierzchu sklepu i psuje każdy zrzut. Zweryfikowane na żywo.
rm -f /etc/xdg/autostart/org.gnome.Tour.desktop
dnf remove -y gnome-tour || true
dnf clean all
fstrim -a || true
%end

poweroff
"""


__all__ = ["FedoraWsBuilder"]

"""Builder Fedora KDE — Kickstart z @^kde-desktop-environment.

Pełna, nienadzorowana instalacja przez ``virt-install --initrd-inject``
(patrz ``vm/build/install-fedora.sh``). Efekt: Plasma + Discover, autologin
użytkownika ``test``, otwarty SSH z kluczem hosta, qemu-guest-agent.

Instalacja kończy się ``poweroff`` (nie ``reboot``) — dzięki temu
``virt-install --wait -1`` wraca dokładnie wtedy, gdy obraz jest gotowy.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from domains.matrix.distro_builders._ssh import load_pubkey, resolve_pubkey_path
from domains.matrix.models import DistroName

if TYPE_CHECKING:
    from pathlib import Path


class FedoraKdeBuilder:
    name = DistroName.FEDORA_KDE

    def __init__(self, ssh_pubkey_path: Path | None = None) -> None:
        self._ssh_pubkey_path = resolve_pubkey_path(ssh_pubkey_path)

    def render_installer(self, out_dir: Path) -> Path:
        target = out_dir / "fedora-kde.ks"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(self._render(), encoding="utf-8")
        return target

    def golden_path(self, images_dir: Path) -> Path:
        return images_dir / "golden" / "fedora-kde.qcow2"

    def _render(self) -> str:
        from jinja2 import Environment, StrictUndefined

        env = Environment(undefined=StrictUndefined)
        return env.from_string(_KICKSTART).render(ssh_pubkey=load_pubkey(self._ssh_pubkey_path))


_KICKSTART = """# Fedora KDE 44 — nienadzorowana instalacja (virt-install --initrd-inject)
url --mirrorlist=https://mirrors.fedoraproject.org/mirrorlist?repo=fedora-44&arch=x86_64
lang en_US.UTF-8
keyboard us
timezone UTC --utc
bootloader --location=mbr
clearpart --all --initlabel
autopart --type=lvm
network --bootproto=dhcp --device=link --activate --hostname=screenwright-fedora-kde
rootpw --lock
user --name=test --password=test --plaintext --gecos="screenwright test" --groups=wheel
{% if ssh_pubkey %}sshkey --username=test "{{ ssh_pubkey }}"
{% endif %}# SSH musi być otwarty: cała diagnostyka i deploy override'ów idzie po nim.
firewall --enabled --service=ssh
services --enabled=sshd,qemu-guest-agent
selinux --enforcing

%packages
@^kde-desktop-environment
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
#
# Fedora 44 KDE NIE używa już SDDM-a: menedżerem jest plasma-login-manager
# (plasmalogin.service), który czyta /etc/plasmalogin.conf.d/. Konfiguracja
# w /etc/sddm.conf.d/ jest przez niego ignorowana — zweryfikowane na żywo,
# maszyna stawała na ekranie logowania mimo poprawnego wpisu dla SDDM-a.
# Piszemy w oba miejsca, żeby obraz działał niezależnie od wersji.
for confdir in /etc/plasmalogin.conf.d /etc/sddm.conf.d; do
    mkdir -p "$confdir"
    cat > "$confdir/autologin.conf" <<'EOF'
[Autologin]
User=test
Session=plasma
EOF
done

# Wygaszacz i lock screen psują deterministyczne zrzuty.
mkdir -p /home/test/.config
cat > /home/test/.config/kscreenlockerrc <<'EOF'
[Daemon]
Autolock=false
LockOnResume=false
EOF
chown -R test:test /home/test/.config

systemctl set-default graphical.target
# initial-setup zablokowałby autologin pytaniami powitalnymi.
systemctl disable initial-setup.service initial-setup-reconfiguration.service || true

# plasma-setup.service PRZEJMUJE seat0 przed autologinem SDDM-a i pokazuje
# kreator „Welcome to Plasma Desktop". Sesja należy wtedy do użytkownika
# `plasma-setup` (uid 980), a nie do `test` — więc Discover uruchomiony po SSH
# nie ma się gdzie narysować i `virsh screenshot` łapie kreator.
# Zweryfikowane na żywo: sama konfiguracja autologinu NIE wystarcza.
systemctl disable plasma-setup.service || true
dnf remove -y plasma-setup || true

# plasma-welcome to odpowiednik gnome-tour: okno powitalne już W sesji,
# lądujące na wierzchu Discovera.
rm -f /etc/xdg/autostart/plasma-welcome.desktop
dnf remove -y plasma-welcome || true
dnf clean all
fstrim -a || true
%end

poweroff
"""


__all__ = ["FedoraKdeBuilder"]

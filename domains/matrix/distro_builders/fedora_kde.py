"""Builder Fedora KDE — Kickstart z @^kde-desktop-environment."""

from __future__ import annotations

from typing import TYPE_CHECKING

from domains.matrix.models import DistroName

if TYPE_CHECKING:
    from pathlib import Path


class FedoraKdeBuilder:
    name = DistroName.FEDORA_KDE

    def render_installer(self, out_dir: Path) -> Path:
        target = out_dir / "fedora-kde.ks"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(_KICKSTART, encoding="utf-8")
        return target

    def golden_path(self, images_dir: Path) -> Path:
        return images_dir / "golden" / "fedora-kde.qcow2"


_KICKSTART = """# Fedora KDE — unattended install via virt-install --initrd-inject
install
url --mirrorlist=https://mirrors.fedoraproject.org/mirrorlist?repo=fedora-44&arch=x86_64
lang en_US.UTF-8
keyboard us
timezone UTC
bootloader --location=mbr
clearpart --all --initlabel
autopart --type=lvm
network --bootproto=dhcp --device=link --activate
rootpw --plaintext screenwright --lock
user --name=test --password=test --plaintext --gecos="screenwright test"

%packages
@^kde-desktop-environment
qemu-guest-agent
spice-vdagent

%post
systemctl enable qemu-guest-agent
systemctl set-default graphical.target
systemctl disable initial-setup.service
%end

reboot
"""


__all__ = ["FedoraKdeBuilder"]

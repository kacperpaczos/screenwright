"""Builder Fedora Workstation — Kickstart z @^workstation-product-environment."""

from __future__ import annotations

from typing import TYPE_CHECKING

from domains.matrix.models import DistroName

if TYPE_CHECKING:
    from pathlib import Path


class FedoraWsBuilder:
    name = DistroName.FEDORA_WS

    def render_installer(self, out_dir: Path) -> Path:
        target = out_dir / "fedora-ws.ks"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(_KICKSTART, encoding="utf-8")
        return target

    def golden_path(self, images_dir: Path) -> Path:
        return images_dir / "golden" / "fedora-ws.qcow2"


_KICKSTART = """# Fedora Workstation — unattended install via virt-install --initrd-inject
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
@^workstation-product-environment
qemu-guest-agent
spice-vdagent

%post
systemctl enable qemu-guest-agent
systemctl set-default graphical.target
systemctl disable initial-setup.service
%end

reboot
"""


__all__ = ["FedoraWsBuilder"]

"""Builder Linux Mint 22 — Ubiquity preseed."""

from __future__ import annotations

from typing import TYPE_CHECKING

from domains.matrix.models import DistroName

if TYPE_CHECKING:
    from pathlib import Path


class MintBuilder:
    name = DistroName.MINT

    def render_installer(self, out_dir: Path) -> Path:
        target = out_dir / "mint-22.preseed.cfg"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(_PRESEED, encoding="utf-8")
        return target

    def golden_path(self, images_dir: Path) -> Path:
        return images_dir / "golden" / "mint-22.qcow2"


_PRESEED = """# Linux Mint 22 — Ubiquity preseed (fragile; locale+keyboard MUST be set)
d-i debian-installer/locale string en_US.UTF-8
d-i keyboard-configuration/xkb-keymap select us
d-i netcfg/choose_interface select auto
d-i mirror/http/hostname string http://packages.linuxmint.com
d-i mirror/http/directory string /

d-i passwd/user-fullname string screenwright
d-i passwd/username string test
d-i passwd/user-password password test
d-i passwd/user-password-again password test
d-i passwd/auto-login boolean true

d-i ubiquity/success_command string \\
    sed -i 's/^#autologin-user=/autologin-user=test/' /etc/lightdm/lightdm.conf.d/*.conf ; \\
    in-target apt-get install -y qemu-guest-agent spice-vdagent ; \\
    in-target systemctl enable qemu-guest-agent

ubiquity ubiquity/summary note
ubiquity ubiquity/reboot boolean true
ubiquity ubiquity/poweroff boolean true
"""


__all__ = ["MintBuilder"]

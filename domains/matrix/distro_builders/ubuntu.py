"""Builder Ubuntu 24.04 — Subiquity autoinstall (cloud-init NoCloud)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from domains.matrix.models import DistroName

if TYPE_CHECKING:
    from pathlib import Path


class UbuntuBuilder:
    name = DistroName.UBUNTU

    def render_installer(self, out_dir: Path) -> Path:
        target = out_dir / "ubuntu-24.04.user-data"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(_USER_DATA, encoding="utf-8")
        return target

    def golden_path(self, images_dir: Path) -> Path:
        return images_dir / "golden" / "ubuntu-24.04.qcow2"


_USER_DATA = """#cloud-config
autoinstall:
  version: 1
  locale: en_US.UTF-8
  keyboard:
    layout: us
  network:
    version: 2
    ethernets:
      default:
        dhcp4: true
  storage:
    layout:
      name: direct
  identity:
    hostname: screenwright
    username: test
    password: "$6$rounds=4096$test$test"
  packages:
    - qemu-guest-agent
    - spice-vdagent
  late-commands:
    - systemctl enable qemu-guest-agent
    - systemctl set-default graphical.target
"""


__all__ = ["UbuntuBuilder"]

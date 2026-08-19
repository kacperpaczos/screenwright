"""Renderer domen XML libvirt (Jinja2)."""

import uuid
from pathlib import Path

from jinja2 import Environment, StrictUndefined

from domains.matrix.models import DomainConfig

TEMPLATE = """<?xml version="1.0" encoding="UTF-8"?>
<domain type="kvm" xmlns:qemu="http://libvirt.org/schemas/domain/qemu/1.0">
  <name>{{ name | e }}</name>
  <uuid>{{ uuid | e }}</uuid>
  <memory unit="MiB">{{ memory_mib }}</memory>
  <vcpu>{{ vcpus }}</vcpu>
  <os>
    <type arch="x86_64">hvm</type>
    <boot dev="hd"/>
  </os>
  <features>
    <acpi/>
    <apic/>
  </features>
  <devices>
    <disk type="file" device="disk">
      <driver name="qemu" type="qcow2"/>
      <source file="{{ disk_path | e }}"/>
      <target dev="vda" bus="virtio"/>
    </disk>
    {% if cdrom_path %}
    <disk type="file" device="cdrom">
      <driver name="qemu" type="raw"/>
      <source file="{{ cdrom_path | e }}"/>
      <target dev="sda" bus="sata"/>
      <readonly/>
    </disk>
    {% endif %}
    <!-- Sieć usermode (passt): w qemu:///session nie ma sieci `default`,
         bo to zasób systemowego libvirtd. passt działa bez roota, a gość
         nie jest routowalny z hosta — dlatego SSH jedzie przez jawne
         przekierowanie portu na 127.0.0.1. -->
    <interface type="user">
      <backend type="passt"/>
      <mac address="{{ mac | e }}"/>
      <model type="virtio"/>
      <portForward proto="tcp" address="127.0.0.1">
        <range start="{{ ssh_port }}" to="22"/>
      </portForward>
    </interface>
    <channel type="unix">
      <target type="virtio" name="org.qemu.guest_agent.0"/>
    </channel>
    <video>
      <model type="virtio"/>
    </video>
    <graphics type="{{ graphics | e }}" autoport="yes" listen="{{ listen | e }}"/>
  </devices>
</domain>
"""


def render_domain_xml(
    config: DomainConfig,
    disk_path: Path,
    cdrom_path: Path | None = None,
) -> str:
    env = Environment(undefined=StrictUndefined)
    template = env.from_string(TEMPLATE)
    return template.render(
        name=config.name,
        uuid=str(uuid.uuid4()),
        memory_mib=config.memory_mib,
        vcpus=config.vcpus,
        disk_path=str(disk_path),
        cdrom_path=str(cdrom_path) if cdrom_path else None,
        mac=_mac(),
        graphics=config.graphics,
        listen=config.listen,
        ssh_port=config.ssh_port,
    )


def _mac() -> str:
    """QEMU OUI (52:54:00) + 3 losowe bajty."""
    last3 = uuid.uuid4().hex[:6]
    return f"52:54:00:{last3[0:2]}:{last3[2:4]}:{last3[4:6]}"


__all__ = ["render_domain_xml"]

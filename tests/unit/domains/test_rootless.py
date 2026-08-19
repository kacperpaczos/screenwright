"""Testy jednostkowe — matryca ma chodzić BEZ uprawnień roota.

Sprawdzone empirycznie na libvirt 12.0 / QEMU 10.2: w ``qemu:///session``
domena wstaje, ``virsh screenshot`` daje realny PNG, a passt przekierowuje
port na 127.0.0.1 — wszystko jako zwykły użytkownik. Te testy pilnują, żeby
kod nie osunął się z powrotem do trybu systemowego, bo to cicha regresja:
wszystko „działa", tylko wymaga admina.
"""

from __future__ import annotations

import re
from pathlib import Path

from domains.matrix.backend.virsh import VirshBackend
from domains.matrix.domain_xml import render_domain_xml
from domains.matrix.models import DistroName, DistroSpec, DomainConfig
from domains.matrix.runner import pick_ssh_port
from shared.settings import DEFAULT_LIBVIRT_URI, Settings


def _domain(**overrides: object) -> DomainConfig:
    base = {"name": "sw-test", "memory_mib": 4096, "vcpus": 2, "disk_gib": 20}
    base.update(overrides)
    return DomainConfig(**base)  # type: ignore[arg-type]


class TestDefaultUri:
    def test_default_is_user_session(self) -> None:
        assert DEFAULT_LIBVIRT_URI == "qemu:///session"

    def test_settings_default(self) -> None:
        assert Settings().libvirt_uri == "qemu:///session"

    def test_virsh_backend_defaults_to_session(self) -> None:
        backend = VirshBackend()
        assert backend._uri == "qemu:///session"

    def test_virsh_backend_uri_still_overridable(self) -> None:
        assert VirshBackend(uri="qemu:///system")._uri == "qemu:///system"

    def test_image_root_lives_in_home(self) -> None:
        """/var/lib/libvirt wymaga roota; HOME nie."""
        root = Settings().image_root
        assert Path.home() in root.parents
        assert "var/lib/libvirt" not in str(root)


class TestDomainXmlNetworking:
    def test_uses_usermode_passt_not_system_network(self) -> None:
        """Sieć `default` to zasób systemowego libvirtd — w session jej nie ma."""
        xml = render_domain_xml(_domain(), Path("/tmp/d.qcow2"))
        assert '<interface type="user">' in xml
        assert '<backend type="passt"/>' in xml
        assert 'type="network"' not in xml
        assert 'network="default"' not in xml

    def test_forwards_ssh_port_to_guest_22(self) -> None:
        """Gość za usermode NAT-em nie jest osiągalny z hosta bez tego."""
        xml = render_domain_xml(_domain(ssh_port=34567), Path("/tmp/d.qcow2"))
        assert '<portForward proto="tcp" address="127.0.0.1">' in xml
        assert '<range start="34567" to="22"/>' in xml

    def test_forward_binds_loopback_only(self) -> None:
        """Bez adresu passt wystawiłby port gościa na wszystkie interfejsy."""
        xml = render_domain_xml(_domain(ssh_port=34567), Path("/tmp/d.qcow2"))
        assert 'address="127.0.0.1"' in xml

    def test_ssh_port_reaches_xml_from_config(self) -> None:
        for port in (2222, 40000, 65535):
            xml = render_domain_xml(_domain(ssh_port=port), Path("/tmp/d.qcow2"))
            assert f'start="{port}"' in xml

    def test_port_is_extractable_the_way_ubuntu_ssh_does_it(self) -> None:
        """`ubuntu-ssh.sh` wyłuskuje port tym samym wzorcem — niech nie zgadują osobno."""
        xml = render_domain_xml(_domain(ssh_port=45678), Path("/tmp/d.qcow2"))
        match = re.search(r'<range start="(\d+)" to="22"', xml)
        assert match is not None
        assert match.group(1) == "45678"


class TestSshPortAllocation:
    def test_returns_usable_port(self) -> None:
        port = pick_ssh_port()
        assert 1024 <= port <= 65535

    def test_ports_differ_between_domains(self) -> None:
        """Dwie domeny z tym samym portem = passt drugiej nie wstanie."""
        ports = {pick_ssh_port() for _ in range(8)}
        assert len(ports) > 1

    def test_allocated_port_passes_model_validation(self) -> None:
        _domain(ssh_port=pick_ssh_port())


class TestSpecPathExpansion:
    def test_tilde_in_golden_image_is_expanded(self) -> None:
        """Obrazy leżą w HOME — spec musi móc to zapisać przenośnie."""
        spec = DistroSpec(
            name=DistroName.UBUNTU,
            golden_image=Path("~/.local/share/screenwright/images/golden/u.qcow2"),
        )
        assert "~" not in str(spec.golden_image)
        assert spec.golden_image.is_absolute()
        assert spec.golden_image.parts[0] == "/"

    def test_tilde_expanded_in_seed_and_artifact(self) -> None:
        spec = DistroSpec(
            name=DistroName.UBUNTU,
            golden_image=Path("~/g.qcow2"),
            seed_iso=Path("~/s.iso"),
            build_artifact=Path("~/b.sh"),
        )
        assert spec.seed_iso is not None
        assert "~" not in str(spec.seed_iso)
        assert spec.build_artifact is not None
        assert "~" not in str(spec.build_artifact)

    def test_none_stays_none(self) -> None:
        spec = DistroSpec(name=DistroName.UBUNTU, golden_image=Path("/tmp/g.qcow2"))
        assert spec.seed_iso is None
        assert spec.build_artifact is None


__all__: list[str] = []

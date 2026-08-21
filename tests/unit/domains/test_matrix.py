"""Testy jednostkowe — matrix: DomainConfig, MatrixRunSpec, MatrixStep, FakeBackend."""

from __future__ import annotations

from pathlib import Path

import pytest
from domains.matrix.backend.fake import FakeBackend
from domains.matrix.models import (
    DistroName,
    DistroSpec,
    DomainConfig,
    MatrixRunSpec,
)
from domains.matrix.runner import plan
from pydantic import ValidationError


def _distro(name: DistroName = DistroName.FEDORA_KDE) -> DistroSpec:
    return DistroSpec(name=name, golden_image=Path("/tmp/golden.qcow2"))


class TestDomainConfig:
    def test_default_graphics_is_vnc(self) -> None:
        cfg = DomainConfig(name="test", memory_mib=2048, vcpus=2, disk_gib=20)
        assert cfg.graphics == "vnc"
        assert cfg.enable_3d is False

    def test_spice_still_allowed(self) -> None:
        cfg = DomainConfig(name="test", memory_mib=2048, vcpus=2, disk_gib=20, graphics="spice")
        assert cfg.graphics == "spice"

    def test_3d_forbidden(self) -> None:
        with pytest.raises(ValidationError):
            DomainConfig(
                name="test",
                memory_mib=2048,
                vcpus=2,
                disk_gib=20,
                graphics="vnc",
                enable_3d=True,  # type: ignore[arg-type]
            )

    def test_memory_bounds(self) -> None:
        with pytest.raises(ValidationError):
            DomainConfig(name="t", memory_mib=100, vcpus=1, disk_gib=10, graphics="vnc")

    def test_invalid_graphics_rejected(self) -> None:
        with pytest.raises(ValidationError):
            DomainConfig(
                name="t",
                memory_mib=2048,
                vcpus=2,
                disk_gib=20,
                graphics="rdp",  # type: ignore[arg-type]
            )


class TestMatrixRunSpec:
    def test_min_apps(self) -> None:
        with pytest.raises(ValidationError):
            MatrixRunSpec(apps=[], distros=[_distro()])

    def test_dry_run_default(self) -> None:
        spec = MatrixRunSpec(apps=["org.kde.kcalc"], distros=[_distro()])
        assert spec.dry_run is True

    def test_duplicate_distros_rejected(self) -> None:
        with pytest.raises(ValidationError):
            MatrixRunSpec(apps=["a"], distros=[_distro(), _distro()])


class TestPlan:
    def test_plan_returns_steps(self) -> None:
        spec = MatrixRunSpec(
            apps=["org.kde.kcalc", "org.gimp.GIMP"],
            distros=[_distro(DistroName.FEDORA_KDE), _distro(DistroName.UBUNTU)],
        )
        steps = plan(spec)
        # Per distro: 3 verbs (create-overlay, create, destroy)
        # Per (distro, app): 3 verbs (qemu-agent-exec, screenshot, verify)
        # Total: 2 distros * (3 + 2 apps * 3) = 2 * 9 = 18
        assert len(steps) == 2 * (3 + 2 * 3)

    def test_plan_starts_with_distro_boot(self) -> None:
        spec = MatrixRunSpec(apps=["a"], distros=[_distro()])
        steps = plan(spec)
        # Pierwsze trzy kroki per dystrybucja to boot/destroy (destroy po boot,
        # przed app-specific verbs — bo VM żyje do końca pętli app).
        assert steps[0].verb == "create-overlay"
        assert steps[1].verb == "create"
        assert steps[2].verb == "destroy"
        # Dalej dopiero verbs per app.
        assert steps[3].verb == "qemu-agent-exec"
        assert steps[-1].verb == "verify"

    def test_plan_sequences_unique(self) -> None:
        spec = MatrixRunSpec(apps=["a"], distros=[_distro()])
        sequences = [s.sequence for s in plan(spec)]
        assert sequences == sorted(sequences)
        assert len(set(sequences)) == len(sequences)


class TestFakeBackend:
    def test_define_then_create_then_start(self) -> None:
        b = FakeBackend()
        b.define("<xml/>", "v1")
        b.create("<xml/>", "v1")
        b.start("v1")
        assert "v1" in b.domains
        assert b.domains["v1"].started

    def test_destroy(self) -> None:
        b = FakeBackend()
        b.define("<xml/>", "v1")
        b.destroy("v1")
        assert b.domains["v1"].destroyed

    def test_calls_recorded(self) -> None:
        b = FakeBackend()
        b.define("<x/>", "v1")
        assert len(b.calls) == 1
        assert b.calls[0].method == "define"

    def test_raise_on(self) -> None:
        b = FakeBackend(raise_on={"screenshot"})
        with pytest.raises(RuntimeError):
            b.screenshot("v1", Path("/tmp/x.png"))

    def test_screenshot_writes(self, tmp_path: Path) -> None:
        b = FakeBackend()
        target = tmp_path / "x.png"
        b.screenshot("v1", target)
        assert target.exists()

    def test_create_overlay_touches_file(self, tmp_path: Path) -> None:
        b = FakeBackend()
        golden = tmp_path / "golden.qcow2"
        golden.write_bytes(b"x" * 1024)
        overlay = tmp_path / "clone.qcow2"
        b.create_overlay(golden, overlay)
        assert overlay.exists()
        assert b.overlays[overlay].golden == golden

    def test_save_and_restore_roundtrip(self, tmp_path: Path) -> None:
        b = FakeBackend()
        b.define("<xml/>", "v1")
        b.start("v1")
        state = tmp_path / "v1.state"
        b.save("v1", state)
        assert state.exists()
        assert b.domains["v1"].saved
        b.destroy("v1")
        assert b.restored_name(state) == "v1"
        assert b.restore(state) is None  # port: restore() -> None, jak VirshBackend
        assert b.domains["v1"].started

    def test_restore_records_xml_override(self, tmp_path: Path) -> None:
        b = FakeBackend()
        b.create("<xml/>", "v1")
        state = tmp_path / "v1.state"
        b.save("v1", state)
        override = tmp_path / "v1.xml"
        override.write_text("<domain><name>v1</name></domain>")
        b.restore(state, xml=override)
        call = next(c for c in b.calls if c.method == "restore")
        assert call.args == (state, override)
        assert b.domains["v1"].xml == "<domain><name>v1</name></domain>"


class TestDistroSpec:
    """`domain_overrides` to jedyne miejsce, gdzie spec mówi o sprzęcie klona.

    Literówka w kluczu albo próba nadania nazwy/portu ma wychodzić przy
    wczytaniu specu — nie po 60 s bootu, gdy virsh odrzuci XML.
    """

    def test_overrides_accept_domain_config_fields(self) -> None:
        spec = DistroSpec(
            name=DistroName.FEDORA_KDE,
            golden_image=Path("/tmp/g.qcow2"),
            domain_overrides={"memory_mib": 2048, "vcpus": 1, "graphics": "spice"},
        )
        assert spec.domain_overrides == {"memory_mib": 2048, "vcpus": 1, "graphics": "spice"}

    @pytest.mark.parametrize("key", ["name", "ssh_port"])
    def test_overrides_reject_runner_owned_fields(self, key: str) -> None:
        with pytest.raises(ValidationError, match="runner-owned"):
            DistroSpec(
                name=DistroName.FEDORA_KDE,
                golden_image=Path("/tmp/g.qcow2"),
                domain_overrides={key: "x"},
            )

    def test_overrides_reject_unknown_key(self) -> None:
        with pytest.raises(ValidationError, match="memory_mb"):
            DistroSpec(
                name=DistroName.FEDORA_KDE,
                golden_image=Path("/tmp/g.qcow2"),
                domain_overrides={"memory_mb": 2048},
            )

    def test_guest_user_defaults_to_test_and_must_be_a_unix_name(self) -> None:
        assert _distro().guest_user == "test"
        spec = DistroSpec(
            name=DistroName.FEDORA_KDE, golden_image=Path("/tmp/g.qcow2"), guest_user="kacper_1"
        )
        assert spec.guest_user == "kacper_1"
        with pytest.raises(ValidationError):
            DistroSpec(
                name=DistroName.FEDORA_KDE,
                golden_image=Path("/tmp/g.qcow2"),
                guest_user="Root User",
            )


class TestFakeBackendGuestSimulation:
    def test_agent_fail_first_records_attempts_then_answers(self) -> None:
        b = FakeBackend(agent_fail_first=2)
        for _ in range(2):
            with pytest.raises(RuntimeError, match="not responding"):
                b.qemu_agent_exec("v1", ["true"])
        assert b.qemu_agent_exec("v1", ["true"]) == ""
        assert len([c for c in b.calls if c.method == "qemu_agent_exec"]) == 3

    def test_raise_on_command_hits_only_matching_argv(self) -> None:
        b = FakeBackend(raise_on_command={"broken-store-command"})
        assert b.qemu_agent_exec("v1", ["true"]) == ""
        with pytest.raises(RuntimeError, match="exitcode=127"):
            b.qemu_agent_exec("v1", ["systemd-run", "--", "broken-store-command"])

    def test_default_probe_answers_simulate_booted_guest(self) -> None:
        b = FakeBackend()
        assert b.qemu_agent_exec("v1", ["id", "-u", "test"]) == "1000"
        assert b.qemu_agent_exec("v1", ["systemctl", "--user", "is-active", "x.target"]) == "active"
        assert b.qemu_agent_exec("v1", ["anything-else"]) == ""

    def test_agent_output_overrides_defaults(self) -> None:
        b = FakeBackend(
            agent_output={"id -u test": "42", "systemctl --user is-active x": "inactive"}
        )
        assert b.qemu_agent_exec("v1", ["id", "-u", "test"]) == "42"
        assert b.qemu_agent_exec("v1", ["systemctl", "--user", "is-active", "x"]) == "inactive"

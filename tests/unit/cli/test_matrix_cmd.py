"""Testy jednostkowe — ładowanie specu i wybór backendu w `cli matrix`."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pytest
from cli.matrix_cmd import (
    _drivers_for_spec,
    _hypervisor_key,
    _load_spec,
    _make_backend,
    _make_shell_factory,
    _resolve_warm_root,
    run_matrix_execute,
    run_matrix_plan,
)
from domains.matrix.backend.fake import FakeBackend, FakeShell
from domains.matrix.backend.ssh import ssh_shell_for
from domains.matrix.backend.virsh import VirshBackend
from domains.matrix.drivers.ubuntu import UbuntuDriver
from domains.matrix.models import DistroName, DistroSpec, DomainConfig

_VALID_SPEC = {
    "apps": ["org.kde.kcalc"],
    "distros": [
        {"name": "ubuntu-24.04", "golden_image": "/tmp/u.qcow2", "store_proxy": "snap-store"}
    ],
}


def _write_spec(tmp_path: Path, payload: object) -> Path:
    path = tmp_path / "spec.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _args(spec: Path, **overrides: object) -> argparse.Namespace:
    base = {
        "spec": str(spec),
        "execute": False,
        "backend": "fake",
        "output": str(spec.parent / "report.json"),
        "store_proxy_port": 8900,
        "cli_serve_base": "http://127.0.0.1:8899",
        "media_dir": str(spec.parent),
        "work_root": str(spec.parent / "runs"),
    }
    base.update(overrides)
    return argparse.Namespace(**base)


class TestLoadSpec:
    def test_reads_seed_iso(self, tmp_path: Path) -> None:
        spec_path = _write_spec(
            tmp_path,
            {
                "apps": ["org.kde.kcalc"],
                "distros": [
                    {
                        "name": "ubuntu-24.04",
                        "golden_image": "/tmp/u.qcow2",
                        "seed_iso": "/tmp/u-seed.iso",
                    }
                ],
            },
        )
        spec = _load_spec(_args(spec_path))
        assert spec.distros[0].seed_iso == Path("/tmp/u-seed.iso")

    def test_seed_iso_defaults_to_none(self, tmp_path: Path) -> None:
        spec = _load_spec(_args(_write_spec(tmp_path, _VALID_SPEC)))
        assert spec.distros[0].seed_iso is None

    def test_missing_file_raises(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError):
            _load_spec(_args(tmp_path / "absent.json"))

    def test_execute_flag_flips_dry_run(self, tmp_path: Path) -> None:
        spec_path = _write_spec(tmp_path, _VALID_SPEC)
        assert _load_spec(_args(spec_path)).dry_run is True
        assert _load_spec(_args(spec_path, execute=True)).dry_run is False

    def test_spec_dry_run_true_survives_execute_flag(self, tmp_path: Path) -> None:
        spec_path = _write_spec(tmp_path, {**_VALID_SPEC, "dry_run": True})
        assert _load_spec(_args(spec_path, execute=True)).dry_run is True

    def test_spec_dry_run_false_without_execute_is_still_dry(self, tmp_path: Path) -> None:
        spec_path = _write_spec(tmp_path, {**_VALID_SPEC, "dry_run": False})
        assert _load_spec(_args(spec_path)).dry_run is True
        assert _load_spec(_args(spec_path, execute=True)).dry_run is False


class TestMakeBackend:
    def test_fake(self) -> None:
        assert isinstance(_make_backend(argparse.Namespace(backend="fake")), FakeBackend)

    def test_virsh(self) -> None:
        assert isinstance(_make_backend(argparse.Namespace(backend="virsh")), VirshBackend)

    def test_unknown_raises(self) -> None:
        with pytest.raises(ValueError, match="unknown backend"):
            _make_backend(argparse.Namespace(backend="podman"))

    def test_fake_backend_gets_fake_shell_on_the_same_screen(self) -> None:
        backend = FakeBackend()
        domain = DomainConfig(name="sw-x", memory_mib=2048, vcpus=1, disk_gib=20)
        distro = DistroSpec(name=DistroName.FEDORA_KDE, golden_image=Path("/tmp/g.qcow2"))
        shell = _make_shell_factory(backend)(domain, distro)
        assert isinstance(shell, FakeShell)
        shell.run(["systemd-run", "--user", "--", "store"])
        assert backend.screen.generation == 1

    def test_virsh_backend_gets_ssh_shell_factory(self) -> None:
        assert _make_shell_factory(VirshBackend()) is ssh_shell_for


class TestDriversForSpec:
    def test_only_distros_present_in_spec(self, tmp_path: Path) -> None:
        spec = _load_spec(_args(_write_spec(tmp_path, _VALID_SPEC)))
        drivers = _drivers_for_spec(spec)
        assert set(drivers) == {DistroName.UBUNTU}
        assert isinstance(drivers[DistroName.UBUNTU], UbuntuDriver)


class TestExitCodes:
    def test_plan_missing_spec_returns_2(self, tmp_path: Path) -> None:
        assert run_matrix_plan(_args(tmp_path / "absent.json")) == 2

    def test_plan_invalid_spec_returns_2(self, tmp_path: Path) -> None:
        bad = _write_spec(tmp_path, {"apps": [], "distros": []})
        assert run_matrix_plan(_args(bad)) == 2

    def test_plan_valid_spec_returns_0(self, tmp_path: Path) -> None:
        assert run_matrix_plan(_args(_write_spec(tmp_path, _VALID_SPEC))) == 0

    def test_execute_unknown_backend_returns_2(self, tmp_path: Path) -> None:
        spec_path = _write_spec(tmp_path, _VALID_SPEC)
        assert run_matrix_execute(_args(spec_path, backend="podman")) == 2

    def test_execute_missing_spec_returns_2(self, tmp_path: Path) -> None:
        assert run_matrix_execute(_args(tmp_path / "absent.json")) == 2

    def test_execute_dry_run_writes_report(self, tmp_path: Path) -> None:
        spec_path = _write_spec(tmp_path, _VALID_SPEC)
        out = tmp_path / "reports" / "matrix.json"
        assert run_matrix_execute(_args(spec_path, output=str(out))) == 0
        report = json.loads(out.read_text(encoding="utf-8"))
        assert report["results"]
        assert [t["phase"] for t in report["timings"]] == ["verify"]

    def test_execute_refused_when_spec_pins_dry_run(self, tmp_path: Path) -> None:
        spec_path = _write_spec(tmp_path, {**_VALID_SPEC, "dry_run": True})
        out = tmp_path / "reports" / "matrix.json"
        assert run_matrix_execute(_args(spec_path, execute=True, output=str(out))) == 2
        assert not out.exists()

    def test_execute_runs_when_spec_dry_run_false(self, tmp_path: Path) -> None:
        # Bez store_proxy: _VALID_SPEC wpiąłby prawdziwy StoreProxyServer (uvicorn),
        # a tu sprawdzamy tylko, że blokada NIE zadziałała.
        spec_path = _write_spec(
            tmp_path,
            {
                "apps": ["org.kde.kcalc"],
                "distros": [{"name": "fedora-kde", "golden_image": "/tmp/x.qcow2"}],
                "dry_run": False,
            },
        )
        out = tmp_path / "reports" / "matrix.json"
        assert run_matrix_execute(_args(spec_path, execute=True, output=str(out))) == 0
        report = json.loads(out.read_text(encoding="utf-8"))
        assert report["results"]


__all__: list[str] = []


class TestWarmCacheFlags:
    def test_fake_backend_has_no_warm_cache_by_default(self) -> None:
        assert _resolve_warm_root(argparse.Namespace(), FakeBackend()) is None

    def test_virsh_backend_defaults_to_image_root_warm(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("SCREENWRIGHT_IMAGE_ROOT", "/imgs")
        assert _resolve_warm_root(argparse.Namespace(), VirshBackend()) == Path("/imgs/warm")

    def test_explicit_root_wins_and_no_warm_cache_disables(self) -> None:
        ns = argparse.Namespace(warm_root="~/w", no_warm_cache=False)
        assert _resolve_warm_root(ns, FakeBackend()) == Path("~/w").expanduser()
        ns = argparse.Namespace(warm_root="~/w", no_warm_cache=True)
        assert _resolve_warm_root(ns, VirshBackend()) is None

    def test_hypervisor_key_is_first_line_or_empty(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import subprocess

        monkeypatch.setattr(
            "cli.matrix_cmd.subprocess.run",
            lambda *a, **k: subprocess.CompletedProcess(
                a, 0, "QEMU emulator version 10.2.2\nCopyright\n", ""
            ),
        )
        assert _hypervisor_key() == "QEMU emulator version 10.2.2"
        monkeypatch.setattr(
            "cli.matrix_cmd.subprocess.run",
            lambda *a, **k: (_ for _ in ()).throw(OSError("no qemu")),
        )
        assert _hypervisor_key() == ""

    def test_execute_with_fake_backend_and_warm_root_builds_template(self, tmp_path: Path) -> None:
        golden = tmp_path / "g.qcow2"
        golden.write_bytes(b"g")
        spec_path = _write_spec(
            tmp_path,
            {
                "apps": ["org.kde.kcalc"],
                "distros": [{"name": "fedora-kde", "golden_image": str(golden)}],
                "dry_run": False,
            },
        )
        out = tmp_path / "report.json"
        rc = run_matrix_execute(
            _args(spec_path, execute=True, output=str(out), warm_root=str(tmp_path / "warm"))
        )
        assert rc == 0
        assert (tmp_path / "warm" / "fedora-kde" / "manifest.json").exists()
        phases = [t["phase"] for t in json.loads(out.read_text())["timings"]]
        assert "warm_save" in phases
        assert "warm_restore" in phases


class TestWorkRoot:
    def test_execute_writes_screenshots_under_work_root(self, tmp_path: Path) -> None:
        spec_path = _write_spec(
            tmp_path,
            {
                "apps": ["org.kde.kcalc"],
                "distros": [{"name": "fedora-kde", "golden_image": "/tmp/x.qcow2"}],
                "dry_run": False,
            },
        )
        out = tmp_path / "report.json"
        assert run_matrix_execute(_args(spec_path, execute=True, output=str(out))) == 0
        report = json.loads(out.read_text())
        shot = Path(report["results"][0]["actual_screenshot"])
        assert shot.parent == tmp_path / "runs"
        assert shot.exists()

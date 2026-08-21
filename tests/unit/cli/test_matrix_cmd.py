"""Testy jednostkowe — ładowanie specu i wybór backendu w `cli matrix`."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pytest
from cli.matrix_cmd import (
    _drivers_for_spec,
    _load_spec,
    _make_backend,
    _make_shell_factory,
    run_matrix_execute,
    run_matrix_plan,
)
from domains.matrix.backend.fake import FakeBackend, FakeShell
from domains.matrix.backend.ssh import ssh_shell_for
from domains.matrix.backend.virsh import VirshBackend
from domains.matrix.drivers.ubuntu import UbuntuDriver
from domains.matrix.models import DistroName

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
        shell = _make_shell_factory(backend)(None, None)  # type: ignore[arg-type]
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

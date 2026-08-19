"""Testy jednostkowe — `cli vm` (operacje operatorskie na domenach libvirt).

`subprocess.run` jest mockowany, bo to granica procesu (virsh / virt-viewer /
skrypty w vm/scripts). Sama konstrukcja komendy jest tym, co testujemy.
"""

from __future__ import annotations

import argparse
import subprocess
from pathlib import Path  # noqa: TC003  (tmp_path w sygnaturach testów)
from typing import Any

import pytest
from cli import vm_cmd
from cli.__main__ import build_parser
from shared.settings import DEFAULT_LIBVIRT_URI


class _Recorder:
    """Podmiana subprocess.run — zapamiętuje argv i oddaje ustalony returncode."""

    def __init__(self, returncode: int = 0) -> None:
        self.returncode = returncode
        self.calls: list[list[str]] = []

    def __call__(self, cmd: list[str], **kwargs: Any) -> subprocess.CompletedProcess[bytes]:
        self.calls.append(list(cmd))
        return subprocess.CompletedProcess(cmd, self.returncode)

    @property
    def argv(self) -> list[str]:
        assert len(self.calls) == 1, f"oczekiwano 1 wywołania, było {len(self.calls)}"
        return self.calls[0]


@pytest.fixture
def recorder(monkeypatch: pytest.MonkeyPatch) -> _Recorder:
    rec = _Recorder()
    monkeypatch.setattr(vm_cmd.subprocess, "run", rec)
    return rec


class TestScriptPath:
    def test_missing_script_raises(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        monkeypatch.setattr(vm_cmd, "_SCRIPTS_DIR", tmp_path)
        with pytest.raises(FileNotFoundError, match="vm script not found"):
            vm_cmd._script_path("nie-ma.sh")

    def test_existing_script_returned(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        (tmp_path / "jest.sh").write_text("#!/bin/sh\n", encoding="utf-8")
        monkeypatch.setattr(vm_cmd, "_SCRIPTS_DIR", tmp_path)
        assert vm_cmd._script_path("jest.sh") == tmp_path / "jest.sh"


class TestVmSsh:
    def test_passes_domain_and_ssh_args(self, recorder: _Recorder) -> None:
        args = argparse.Namespace(name="sw-ubuntu-1", ssh_args=["--", "snap", "version"])
        assert vm_cmd.run_vm_ssh(args) == 0
        assert recorder.argv[0].endswith("ubuntu-ssh.sh")
        assert recorder.argv[1:] == ["sw-ubuntu-1", "--", "snap", "version"]

    def test_propagates_returncode(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(vm_cmd.subprocess, "run", _Recorder(returncode=3))
        args = argparse.Namespace(name="sw-ubuntu-1", ssh_args=[])
        assert vm_cmd.run_vm_ssh(args) == 3


class TestVmView:
    def test_missing_virt_viewer_returns_1(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(vm_cmd.shutil, "which", lambda _name: None)
        assert vm_cmd.run_vm_view(argparse.Namespace(name="sw-ubuntu-1")) == 1

    def test_invokes_virt_viewer_on_system_uri(
        self, monkeypatch: pytest.MonkeyPatch, recorder: _Recorder
    ) -> None:
        monkeypatch.setattr(vm_cmd.shutil, "which", lambda _name: "/usr/bin/virt-viewer")
        assert vm_cmd.run_vm_view(argparse.Namespace(name="sw-ubuntu-1")) == 0
        assert recorder.argv == ["virt-viewer", "-c", DEFAULT_LIBVIRT_URI, "sw-ubuntu-1"]
        assert DEFAULT_LIBVIRT_URI == "qemu:///session", "matryca ma chodzić bez roota"


class TestVmSnapshot:
    def test_calls_virsh_screenshot(self, recorder: _Recorder, tmp_path: Path) -> None:
        out = tmp_path / "shots" / "kcalc.png"
        args = argparse.Namespace(name="sw-ubuntu-1", output=str(out))
        assert vm_cmd.run_vm_snapshot(args) == 0
        assert recorder.argv == [
            "virsh",
            "-c",
            DEFAULT_LIBVIRT_URI,
            "screenshot",
            "sw-ubuntu-1",
            str(out),
        ]

    def test_creates_output_directory(self, recorder: _Recorder, tmp_path: Path) -> None:
        out = tmp_path / "glebiej" / "jeszcze" / "kcalc.png"
        vm_cmd.run_vm_snapshot(argparse.Namespace(name="d", output=str(out)))
        assert out.parent.is_dir()


class TestVmDiagnose:
    def test_print_flag(self, recorder: _Recorder) -> None:
        args = argparse.Namespace(name="sw-ubuntu-1", output=None, print=True)
        assert vm_cmd.run_vm_diagnose(args) == 0
        assert recorder.argv[0].endswith("diagnose-ubuntu.sh")
        assert recorder.argv[1:] == ["sw-ubuntu-1", "--print"]

    def test_output_flag(self, recorder: _Recorder, tmp_path: Path) -> None:
        out = tmp_path / "raport.json"
        args = argparse.Namespace(name="sw-ubuntu-1", output=str(out), print=False)
        vm_cmd.run_vm_diagnose(args)
        assert recorder.argv[1:] == ["sw-ubuntu-1", "--output", str(out)]


class TestParserWiring:
    @pytest.mark.parametrize(
        ("argv", "expected"),
        [
            (["vm", "ssh", "d"], vm_cmd.run_vm_ssh),
            (["vm", "view", "d"], vm_cmd.run_vm_view),
            (["vm", "snapshot", "d", "o.png"], vm_cmd.run_vm_snapshot),
            (["vm", "diagnose", "d"], vm_cmd.run_vm_diagnose),
        ],
    )
    def test_subcommand_dispatches_to_handler(self, argv: list[str], expected: object) -> None:
        args = build_parser().parse_args(argv)
        assert args.func is expected

    def test_vm_requires_action(self) -> None:
        with pytest.raises(SystemExit):
            build_parser().parse_args(["vm"])


__all__: list[str] = []

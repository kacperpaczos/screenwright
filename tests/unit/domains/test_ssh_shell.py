"""Testy jednostkowe — SshShell (mock subprocess) i rozwiązywanie klucza prywatnego."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

import pytest
from domains.matrix.backend.ssh import SshShell, ssh_shell_for
from domains.matrix.distro_builders._ssh import (
    DEFAULT_PRIVKEY,
    PRIVKEY_ENV_VAR,
    resolve_private_key_path,
)
from domains.matrix.models import DistroName, DistroSpec, DomainConfig


class _FakeRun:
    def __init__(self, rc: int = 0, stdout: str = "", stderr: str = "") -> None:
        self.calls: list[dict[str, Any]] = []
        self._result = subprocess.CompletedProcess(
            args=[], returncode=rc, stdout=stdout, stderr=stderr
        )

    def __call__(self, args: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        self.calls.append({"args": args, "kwargs": kwargs})
        return self._result


class TestSshShell:
    def test_builds_non_interactive_ssh_argv(self, monkeypatch: pytest.MonkeyPatch) -> None:
        run = _FakeRun(stdout="active\n")
        monkeypatch.setattr("domains.matrix.backend.ssh.subprocess.run", run)
        shell = SshShell(port=48241, user="test", key=Path("/k/id"))
        out = shell.run(["systemctl", "--user", "is-active", "graphical-session.target"], timeout=7)
        assert out == "active\n"
        (call,) = run.calls
        argv = call["args"]
        assert argv[0] == "ssh"
        assert argv[1:3] == ["-i", "/k/id"]
        assert argv[3:5] == ["-p", "48241"]
        assert "BatchMode=yes" in argv
        assert "StrictHostKeyChecking=no" in argv
        assert "UserKnownHostsFile=/dev/null" in argv
        assert argv[-3:] == [
            "test@127.0.0.1",
            "--",
            "systemctl --user is-active graphical-session.target",
        ]
        assert call["kwargs"]["timeout"] == 7
        assert call["kwargs"]["check"] is False

    def test_quotes_arguments_for_the_remote_shell(self, monkeypatch: pytest.MonkeyPatch) -> None:
        run = _FakeRun()
        monkeypatch.setattr("domains.matrix.backend.ssh.subprocess.run", run)
        SshShell(port=2222, user="test", key=Path("/k")).run(["sh", "-c", "echo a b"])
        assert run.calls[0]["args"][-1] == "sh -c 'echo a b'"

    def test_nonzero_exit_raises_with_stderr(self, monkeypatch: pytest.MonkeyPatch) -> None:
        run = _FakeRun(rc=3, stderr="inactive")
        monkeypatch.setattr("domains.matrix.backend.ssh.subprocess.run", run)
        with pytest.raises(RuntimeError, match=r"test@127.0.0.1:2222 .* \(exit=3\): inactive"):
            SshShell(port=2222, user="test", key=Path("/k")).run(
                ["systemctl", "--user", "is-active", "x"]
            )


class TestSshShellFor:
    def test_uses_domain_port_guest_user_and_env_key(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv(PRIVKEY_ENV_VAR, "/tmp/some.key")
        domain = DomainConfig(name="sw-x", memory_mib=2048, vcpus=1, disk_gib=20, ssh_port=40001)
        distro = DistroSpec(
            name=DistroName.FEDORA_KDE, golden_image=Path("/tmp/g.qcow2"), guest_user="kacper"
        )
        shell = ssh_shell_for(domain, distro)
        assert shell.target == "kacper@127.0.0.1:40001"
        run = _FakeRun()
        monkeypatch.setattr("domains.matrix.backend.ssh.subprocess.run", run)
        shell.run(["true"])
        assert run.calls[0]["args"][1:3] == ["-i", "/tmp/some.key"]


class TestResolvePrivateKeyPath:
    def test_explicit_wins(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv(PRIVKEY_ENV_VAR, "/env/key")
        assert resolve_private_key_path(Path("/x/key")) == Path("/x/key")

    def test_env_then_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv(PRIVKEY_ENV_VAR, "/env/key")
        assert resolve_private_key_path() == Path("/env/key")
        monkeypatch.delenv(PRIVKEY_ENV_VAR)
        assert resolve_private_key_path() == DEFAULT_PRIVKEY
        assert (
            DEFAULT_PRIVKEY.name == "screenwright_ubuntu"
        )  # ten sam klucz, co vm/scripts/ubuntu-ssh.sh

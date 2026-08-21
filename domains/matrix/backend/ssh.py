"""SshShell — komendy w gościu jako użytkownik sesji, przez przekierowany port passt.

Te same opcje, co ``vm/scripts/ubuntu-ssh.sh``: klucz z ``SCREENWRIGHT_SSH_KEY``
(domyślnie ``~/.ssh/screenwright_ubuntu``), ``127.0.0.1:<ssh_port>``, bez
known_hosts (każdy klon ma nowy klucz hosta), ``BatchMode`` — żeby brak klucza
był błędem, a nie pytaniem o hasło, na które nikt nie odpowie.
"""

from __future__ import annotations

import shlex
import subprocess
from typing import TYPE_CHECKING

from shared.logging import log_entry

from domains.matrix.distro_builders._ssh import resolve_private_key_path

if TYPE_CHECKING:
    from pathlib import Path

    from domains.matrix.models import DistroSpec, DomainConfig


class SshShell:
    """``ssh -p <port> <user>@127.0.0.1 -- <cmd>`` z kluczem i bez interakcji."""

    def __init__(
        self,
        *,
        port: int,
        user: str,
        key: Path,
        host: str = "127.0.0.1",
        connect_timeout: float = 10.0,
    ) -> None:
        self._port = port
        self._user = user
        self._key = key
        self._host = host
        self._connect_timeout = connect_timeout

    @property
    def target(self) -> str:
        return f"{self._user}@{self._host}:{self._port}"

    def run(self, command: list[str], timeout: float = 30.0) -> str:
        argv = [
            "ssh",
            "-i",
            str(self._key),
            "-p",
            str(self._port),
            "-o",
            "IdentitiesOnly=yes",
            "-o",
            "BatchMode=yes",
            "-o",
            "StrictHostKeyChecking=no",
            "-o",
            "UserKnownHostsFile=/dev/null",
            "-o",
            "LogLevel=ERROR",
            "-o",
            f"ConnectTimeout={self._connect_timeout:g}",
            f"{self._user}@{self._host}",
            "--",
            shlex.join(command),
        ]
        log_entry(20, "matrix.ssh", target=self.target, command=command)
        result = subprocess.run(argv, capture_output=True, text=True, timeout=timeout, check=False)
        if result.returncode != 0:
            raise RuntimeError(
                f"ssh {self.target} {shlex.join(command)} failed (exit={result.returncode}): "
                f"{result.stderr.strip()}"
            )
        return result.stdout


def ssh_shell_for(domain: DomainConfig, distro: DistroSpec) -> SshShell:
    """Domyślna fabryka runnera: port z XML-a klona, użytkownik z ``DistroSpec``."""
    return SshShell(port=domain.ssh_port, user=distro.guest_user, key=resolve_private_key_path())


__all__ = ["SshShell", "ssh_shell_for"]

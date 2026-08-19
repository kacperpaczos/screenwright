"""Adapter Virsh — wywołuje `virsh` i `qemu-img` przez subprocess.

Importowany leniwie (TYPE_CHECKING w testach suchego przebiegu).
"""

from __future__ import annotations

import base64
import json
import subprocess
import time
from typing import TYPE_CHECKING

from shared.logging import log_entry
from shared.settings import DEFAULT_LIBVIRT_URI

if TYPE_CHECKING:
    from pathlib import Path


class VirshBackend:
    """Wywołuje `virsh` i `qemu-img` z subprocess (tylko gdy uruchomiony w buildzie)."""

    def __init__(self, uri: str = DEFAULT_LIBVIRT_URI) -> None:
        self._uri = uri

    def _run(
        self,
        args: list[str],
        *,
        stdin: str | None = None,
        timeout: float | None = None,
        check: bool = True,
    ) -> subprocess.CompletedProcess[str]:
        log_entry(20, "matrix.virsh", args=args)
        return subprocess.run(
            ["virsh", "-c", self._uri, *args],
            check=check,
            capture_output=True,
            text=True,
            input=stdin,
            timeout=timeout,
        )

    def _qemu_img(self, args: list[str]) -> subprocess.CompletedProcess[str]:
        log_entry(20, "matrix.qemu_img", args=args)
        return subprocess.run(
            ["qemu-img", *args],
            check=True,
            capture_output=True,
            text=True,
        )

    def create_overlay(self, golden: Path, overlay: Path) -> None:
        """Tworzy qcow2 overlay wskazujący na golden image (backing file)."""
        overlay.parent.mkdir(parents=True, exist_ok=True)
        self._qemu_img(
            [
                "create",
                "-f",
                "qcow2",
                "-F",
                "qcow2",
                "-b",
                str(golden),
                str(overlay),
            ]
        )

    def define(self, xml: str, name: str) -> None:
        self._run(["define", "/dev/stdin"], stdin=xml)

    def create(self, xml: str, name: str) -> None:
        """Definiuje i uruchamia domenę transient. Po destroy znika z libvirtd."""
        self._run(["create", "/dev/stdin"], stdin=xml)

    def start(self, name: str) -> None:
        self._run(["start", name])

    def destroy(self, name: str) -> None:
        self._run(["destroy", name])

    def save(self, name: str, state_file: Path) -> None:
        """Zapisuje RAM domeny do pliku i wyłącza ją. Działa dla transient.

        Format pliku (domyślnie `raw`) jest duży — ustaw `save_image_format =
        "zstd"` w `/etc/libvirt/qemu.conf` dla ~2x kompresji.
        """
        self._run(["save", name, str(state_file)])

    def restore(self, state_file: Path) -> None:
        """Przywraca domenę z pliku stanu. Po restore domena jest nie-transient."""
        self._run(["restore", str(state_file)])

    def screenshot(self, name: str, out_path: Path) -> Path:
        self._run(["screenshot", name, str(out_path)])
        return out_path

    def domifaddr(self, name: str) -> str:
        result = self._run(["domifaddr", name, "--source", "agent"])
        return result.stdout.strip()

    def qemu_agent_exec(self, name: str, command: list[str], timeout: float = 30.0) -> str:
        """Wykonuje komendę w gościu przez qemu-guest-agent.

        Protokół (zweryfikowany na żywej VM):
        1. `guest-exec` jako surowy JSON → odpowiedź `{"return": {"pid": N}}`.
           Payload MUSI być surowym JSON, virsh sam dodaje opakowanie.
        2. `guest-exec-status` z `{"pid": N}` w pętli z limitem `timeout` —
           `wait: true` nie istnieje w agencie (agent zwraca "Parameter 'wait'
           is unexpected"). Dopóki `exited` jest false, odpowiedź nie ma
           `exitcode` ani `out-data` — nie wolno ich wtedy odczytywać.
        3. Po `exited: true` dekodujemy `out-data` z base64. Jeśli exitcode
           != 0, rzucamy RuntimeError z treścią stderr.

        Parametr `timeout` ogranicza łączny czas oczekiwania na wyjście
        procesu w gościu (czas wall-clock). Zawieszony virsh lub gość
        przerywa wywołanie po `timeout` sekundach — bez tego jedna
        zawieszona komenda zawiesiłaby całą matrycę.
        """
        exec_payload = json.dumps(
            {
                "execute": "guest-exec",
                "arguments": {
                    "path": command[0],
                    "arg": command[1:],
                    "capture-output": True,
                },
            }
        )
        exec_result = self._run(
            ["qemu-agent-command", name, exec_payload], timeout=timeout, check=False
        )
        if exec_result.returncode != 0 or not exec_result.stdout.strip():
            err = exec_result.stderr.strip() or "empty stdout"
            raise RuntimeError(
                f"guest-exec on {name} failed (virsh exit={exec_result.returncode}): {err}"
            )
        exec_resp = json.loads(exec_result.stdout)
        if "return" not in exec_resp or "pid" not in exec_resp.get("return", {}):
            raise RuntimeError(
                f"guest-exec on {name} returned unexpected response: {exec_result.stdout!r}"
            )
        pid = exec_resp["return"]["pid"]

        deadline = time.monotonic() + timeout
        info: dict[str, object] = {}
        while True:
            status_payload = json.dumps(
                {
                    "execute": "guest-exec-status",
                    "arguments": {"pid": pid},
                }
            )
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError(
                    f"guest-exec on {name} pid={pid} did not finish within {timeout}s"
                )
            status_result = self._run(
                ["qemu-agent-command", name, status_payload], timeout=remaining + 5
            )
            status_resp = json.loads(status_result.stdout)
            info = status_resp["return"]
            if info.get("exited") is True:
                break
            time.sleep(min(0.2, max(0.0, remaining)))

        stdout_bytes = base64.b64decode(info.get("out-data", "")) if info.get("out-data") else b""
        stderr_bytes = base64.b64decode(info.get("err-data", "")) if info.get("err-data") else b""
        exitcode = info.get("exitcode", 0)

        if exitcode != 0:
            stderr = stderr_bytes.decode("utf-8", errors="replace")
            raise RuntimeError(
                f"guest-exec failed (exitcode={exitcode}) on {name}: {stderr.strip()}"
            )

        return stdout_bytes.decode("utf-8", errors="replace")


__all__ = ["VirshBackend"]

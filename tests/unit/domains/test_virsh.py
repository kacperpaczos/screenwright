"""Testy jednostkowe VirshBackend — mockujemy subprocess.

To jest bariera regresji dla czterech potwierdzonych bugów:
1. `define` / `create` muszą podać XML przez stdin (`input=xml`).
2. `qemu_agent_exec` musi wysłać surowy JSON (nie base64) i wywołać
   `guest-exec-status` oraz zdekodować base64 z `out-data`.
3. Nazwa domeny podawana do virsh musi zgadzać się z nazwą w XML.
4. `save` / `restore` to jedyne sensowne zastępstwo managedsave dla domen
   transient (libvirt odmawia managedsave dla transient).
"""

from __future__ import annotations

import base64
import json
import subprocess
from pathlib import Path
from typing import Any

import pytest
from domains.matrix.backend.virsh import VirshBackend


def _completed(args: list[str], stdout: str = "", stderr: str = "", rc: int = 0) -> Any:
    cp = subprocess.CompletedProcess(args=args, returncode=rc, stdout=stdout, stderr=stderr)
    return cp


class _FakePopen:
    """Kontrolowany fake Popen: zwraca zaprogramowane stdout dla każdego virsh call."""

    def __init__(self, responses: list[subprocess.CompletedProcess[str]]) -> None:
        self._responses = list(responses)
        self.calls: list[dict[str, Any]] = []

    def __call__(self, args: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        self.calls.append({"args": args, "kwargs": kwargs})
        if not self._responses:
            raise AssertionError(f"unexpected extra call: {args}")
        return self._responses.pop(0)


def test_define_pipes_xml_through_stdin(monkeypatch: pytest.MonkeyPatch) -> None:
    popen = _FakePopen([_completed(["virsh", "define"])])
    monkeypatch.setattr("subprocess.run", popen)
    VirshBackend().define("<domain/>", "v1")
    assert len(popen.calls) == 1
    kwargs = popen.calls[0]["kwargs"]
    assert kwargs["input"] == "<domain/>"
    assert kwargs["check"] is True
    assert "stdin" not in kwargs or kwargs.get("stdin") is None


def test_create_pipes_xml_through_stdin(monkeypatch: pytest.MonkeyPatch) -> None:
    popen = _FakePopen([_completed(["virsh", "create"])])
    monkeypatch.setattr("subprocess.run", popen)
    VirshBackend().create("<domain/>", "v1")
    assert popen.calls[0]["kwargs"]["input"] == "<domain/>"


def test_qemu_agent_exec_sends_raw_json_not_base64(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Potwierdza odwrócenie protokołu: payload jest surowym JSON, virsh sam koduje.

    Drugie wywołanie (guest-exec-status) NIE zawiera `wait` — agent odrzuca
    to z "Parameter 'wait' is unexpected". Status jest odpytywany w pętli.
    """
    exec_stdout = json.dumps({"return": {"pid": 1220}})
    out_b64 = base64.b64encode(b"screenwright-ok\n").decode()
    status_stdout = json.dumps(
        {"return": {"exited": True, "exitcode": 0, "out-data": out_b64, "err-data": ""}}
    )
    popen = _FakePopen(
        [
            _completed(["virsh", "qemu-agent-command"], stdout=exec_stdout),
            _completed(["virsh", "qemu-agent-command"], stdout=status_stdout),
        ]
    )
    monkeypatch.setattr("subprocess.run", popen)

    backend = VirshBackend()
    result = backend.qemu_agent_exec("v1", ["/usr/bin/true"])
    assert result == "screenwright-ok\n"

    # Pierwsze wywołanie: surowy JSON do qemu-agent-command (virsh sam opakowuje).
    first_args = popen.calls[0]["args"]
    # format: ["virsh", "-c", URI, "qemu-agent-command", "v1", "<raw-json>"]
    assert first_args[0] == "virsh"
    assert first_args[3:5] == ["qemu-agent-command", "v1"]
    raw_payload = first_args[-1]
    decoded = json.loads(raw_payload)
    assert decoded["execute"] == "guest-exec"
    assert decoded["arguments"]["path"] == "/usr/bin/true"
    # Ani razu nie wolno nam base64-kodować payloadu w naszym kodzie.
    assert raw_payload == json.dumps(decoded)

    # Drugie wywołanie: guest-exec-status z prawdziwym pid, BEZ `wait`.
    second_args = popen.calls[1]["args"]
    status_decoded = json.loads(second_args[-1])
    assert status_decoded["execute"] == "guest-exec-status"
    assert status_decoded["arguments"]["pid"] == 1220
    assert "wait" not in status_decoded["arguments"]


def test_qemu_agent_exec_polls_until_exited(monkeypatch: pytest.MonkeyPatch) -> None:
    """Gdy pierwszy status mówi exited=false (komenda jeszcze trwa),
    runner musi odpytać ponownie. Wyjście pojawia się dopiero w odpowiedzi
    z exited=true — i tylko wtedy wolno czytać out-data."""
    exec_stdout = json.dumps({"return": {"pid": 42}})
    running_stdout = json.dumps({"return": {"exited": False}})
    done_stdout = json.dumps(
        {
            "return": {
                "exited": True,
                "exitcode": 0,
                "out-data": base64.b64encode(b"result\n").decode(),
                "err-data": "",
            }
        }
    )
    popen = _FakePopen(
        [
            _completed(["virsh"], stdout=exec_stdout),
            _completed(["virsh"], stdout=running_stdout),
            _completed(["virsh"], stdout=done_stdout),
        ]
    )
    monkeypatch.setattr("subprocess.run", popen)
    # Zerowy sleep żeby pętla nie czekała.
    monkeypatch.setattr("time.sleep", lambda _: None)

    out = VirshBackend().qemu_agent_exec("v1", ["/bin/sh", "-c", "sleep 1"])
    assert out == "result\n"
    # Trzy wywołania subprocess.run: exec + dwa statusy.
    assert len(popen.calls) == 3


def test_qemu_agent_exec_exits_on_silent_running(monkeypatch: pytest.MonkeyPatch) -> None:
    """Pułapka: gdy agent zwraca tylko {"exited": false}, nie ma exitcode ani
    out-data. Poprzedni kod używał info.get('exitcode', 0) co dawało cichy
    fałszywy pass. Nowy kod musi czekać aż exited będzie True lub timeout."""
    exec_stdout = json.dumps({"return": {"pid": 7}})
    running_stdout = json.dumps({"return": {"exited": False}})

    def fake_run(*args: object, **kwargs: object) -> Any:
        # Pierwsze wywołanie: guest-exec → pid 7. Każde następne: exited=False.
        fake_run.count = getattr(fake_run, "count", 0) + 1  # type: ignore[attr-defined]
        if fake_run.count == 1:  # type: ignore[attr-defined]
            return _completed(["virsh"], stdout=exec_stdout)
        return _completed(["virsh"], stdout=running_stdout)

    monkeypatch.setattr("subprocess.run", fake_run)
    monkeypatch.setattr("time.sleep", lambda _: None)
    # Wymuś monotonic żeby deadline minął po pierwszej iteracji.
    counter = {"n": 0}
    real_monotonic = __import__("time").monotonic

    def fake_monotonic() -> float:
        counter["n"] += 1
        return real_monotonic() + counter["n"] * 1.0  # każde wywołanie przesuwa czas

    monkeypatch.setattr("time.monotonic", fake_monotonic)

    backend = VirshBackend()
    with pytest.raises(TimeoutError, match="did not finish"):
        backend.qemu_agent_exec("v1", ["/bin/true"], timeout=0.001)


def test_qemu_agent_exec_decodes_base64_out_data(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    exec_stdout = json.dumps({"return": {"pid": 7}})
    expected = "stdout-line1\nstdout-line2\n"
    status_stdout = json.dumps(
        {
            "return": {
                "exited": True,
                "exitcode": 0,
                "out-data": base64.b64encode(expected.encode()).decode(),
                "err-data": "",
            }
        }
    )
    popen = _FakePopen(
        [
            _completed(["virsh"], stdout=exec_stdout),
            _completed(["virsh"], stdout=status_stdout),
        ]
    )
    monkeypatch.setattr("subprocess.run", popen)
    result = VirshBackend().qemu_agent_exec("v1", ["/bin/echo", "x"])
    assert result == expected


def test_qemu_agent_exec_raises_on_nonzero_exitcode(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    exec_stdout = json.dumps({"return": {"pid": 9}})
    err_b64 = base64.b64encode(b"boom: command not found\n").decode()
    status_stdout = json.dumps(
        {
            "return": {
                "exited": True,
                "exitcode": 127,
                "out-data": "",
                "err-data": err_b64,
            }
        }
    )
    popen = _FakePopen(
        [
            _completed(["virsh"], stdout=exec_stdout),
            _completed(["virsh"], stdout=status_stdout),
        ]
    )
    monkeypatch.setattr("subprocess.run", popen)
    backend = VirshBackend()
    with pytest.raises(RuntimeError, match="exitcode=127"):
        backend.qemu_agent_exec("v1", ["/no/such/binary"])


def test_create_overlay_calls_qemu_img_with_backing_file(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    golden = tmp_path / "golden.qcow2"
    overlay = tmp_path / "clone.qcow2"
    popen = _FakePopen([_completed(["qemu-img"])])
    monkeypatch.setattr("subprocess.run", popen)
    VirshBackend().create_overlay(golden, overlay)
    args = popen.calls[0]["args"]
    assert args[0] == "qemu-img"
    assert "create" in args
    assert "-b" in args
    assert str(golden) in args
    assert str(overlay) in args


def test_save_and_restore_use_state_file(monkeypatch: pytest.MonkeyPatch) -> None:
    popen = _FakePopen(
        [
            _completed(["virsh", "save"]),
            _completed(["virsh", "restore"]),
        ]
    )
    monkeypatch.setattr("subprocess.run", popen)
    backend = VirshBackend()
    state = Path("/tmp/v1.state")
    backend.save("v1", state)
    backend.restore(state)
    save_args = popen.calls[0]["args"]
    restore_args = popen.calls[1]["args"]
    assert save_args[0] == "virsh"
    assert save_args[3:] == ["save", "v1", str(state)]
    assert restore_args[3:] == ["restore", str(state)]


def test_start_destroy_use_unified_name(monkeypatch: pytest.MonkeyPatch) -> None:
    """Nazwa domeny podawana do virsh jest spójna (definiuje ją caller)."""
    popen = _FakePopen(
        [
            _completed(["virsh", "start"]),
            _completed(["virsh", "destroy"]),
        ]
    )
    monkeypatch.setattr("subprocess.run", popen)
    backend = VirshBackend()
    backend.start("sw-fedora-kde-a3b4c5")
    backend.destroy("sw-fedora-kde-a3b4c5")
    assert popen.calls[0]["args"][-1] == "sw-fedora-kde-a3b4c5"
    assert popen.calls[1]["args"][-1] == "sw-fedora-kde-a3b4c5"

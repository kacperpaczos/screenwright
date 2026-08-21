"""Testy jednostkowe — domains.matrix.guest: gotowość gościa, sesja, settle."""

from __future__ import annotations

import time
from pathlib import Path  # noqa: TC003  (tmp_path / fixtures at runtime)

import pytest
from domains.matrix.backend.fake import FakeBackend
from domains.matrix.guest import (
    GuestSession,
    GuestWaits,
    resolve_session,
    session_command,
    session_probe,
    settle_screenshot,
    wait_for_agent,
    wait_for_session,
)

_SESSION = GuestSession(user="test", uid=1000)


def _agent_calls(backend: FakeBackend) -> list[list[str]]:
    return [c.args[1] for c in backend.calls if c.method == "qemu_agent_exec"]


class TestGuestWaits:
    def test_default_is_instant_in_test_mode(self) -> None:
        # autouse fixture ustawia SCREENWRIGHT_TESTS_FAST=1
        waits = GuestWaits.default()
        assert waits.clock is not time.monotonic
        before = waits.clock()
        waits.sleep(100.0)
        assert waits.clock() == before + 100.0

    def test_default_is_real_outside_test_mode(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("SCREENWRIGHT_TESTS_FAST", raising=False)
        waits = GuestWaits.default()
        assert waits.clock is time.monotonic
        assert waits.sleep is time.sleep

    def test_instant_accepts_overrides(self) -> None:
        waits = GuestWaits.instant(agent_timeout=5.0, stable_frames=3)
        assert waits.agent_timeout == 5.0
        assert waits.stable_frames == 3


class TestWaitForAgent:
    def test_retries_until_agent_answers(self) -> None:
        backend = FakeBackend(agent_fail_first=3)
        wait_for_agent(backend, "vm", waits=GuestWaits.instant())
        calls = _agent_calls(backend)
        assert len(calls) == 4
        assert all(c == ["true"] for c in calls)

    def test_times_out_with_last_error_in_message(self) -> None:
        backend = FakeBackend(agent_fail_first=10**6)
        waits = GuestWaits.instant(agent_timeout=5.0, probe_interval=1.0)
        with pytest.raises(TimeoutError, match=r"did not answer within 5s.*not responding"):
            wait_for_agent(backend, "vm", waits=waits)
        assert waits.clock() >= 5.0
        assert len(_agent_calls(backend)) == 6


class TestResolveSession:
    def test_reads_uid_from_guest(self) -> None:
        backend = FakeBackend(agent_output={"id -u kacper": "1001\n"})
        session = resolve_session(backend, "vm", "kacper", waits=GuestWaits.instant())
        assert session == GuestSession(user="kacper", uid=1001)
        assert session.runtime_dir == "/run/user/1001"

    def test_fake_defaults_to_uid_1000(self) -> None:
        session = resolve_session(FakeBackend(), "vm", "test", waits=GuestWaits.instant())
        assert session.uid == 1000

    def test_garbage_uid_is_an_error(self) -> None:
        backend = FakeBackend(agent_output={"id -u test": "id: 'test': no such user"})
        with pytest.raises(RuntimeError, match="cannot resolve uid"):
            resolve_session(backend, "vm", "test", waits=GuestWaits.instant())


class TestWaitForSession:
    def test_probe_runs_systemctl_as_the_user(self) -> None:
        probe = session_probe(_SESSION)
        assert probe[:4] == ["runuser", "-u", "test", "--"]
        assert "XDG_RUNTIME_DIR=/run/user/1000" in probe
        assert probe[-4:] == ["systemctl", "--user", "is-active", "graphical-session.target"]

    def test_nonzero_exit_then_active(self) -> None:
        # systemctl is-active kończy się kodem 3 (→ RuntimeError z backendu), dopóki target nie wstanie.
        backend = FakeBackend(agent_fail_first=2)
        wait_for_session(backend, "vm", _SESSION, waits=GuestWaits.instant())
        assert len(_agent_calls(backend)) == 3

    def test_inactive_answer_keeps_polling_then_times_out(self) -> None:
        key = " ".join(session_probe(_SESSION))
        backend = FakeBackend(agent_output={key: "inactive\n"})
        waits = GuestWaits.instant(session_timeout=3.0, probe_interval=1.0)
        with pytest.raises(TimeoutError, match=r"not active after 3s.*'inactive'"):
            wait_for_session(backend, "vm", _SESSION, waits=waits)


class TestSessionCommand:
    def test_wraps_argv_with_runuser_env_and_systemd_run(self) -> None:
        cmd = session_command(
            ["plasma-discover", "--application=appstream:x"], _SESSION, wait=False
        )
        assert cmd == [
            "runuser",
            "-u",
            "test",
            "--",
            "env",
            "XDG_RUNTIME_DIR=/run/user/1000",
            "DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/1000/bus",
            "systemd-run",
            "--user",
            "--collect",
            "--quiet",
            "--",
            "plasma-discover",
            "--application=appstream:x",
        ]

    def test_wait_flag_blocks_until_exit(self) -> None:
        cmd = session_command(["gnome-software", "--quit"], _SESSION, wait=True)
        assert "--wait" in cmd
        assert cmd.index("--wait") < cmd.index("--", 4)
        assert cmd[-2:] == ["gnome-software", "--quit"]

    def test_other_user_and_uid(self) -> None:
        cmd = session_command(["true"], GuestSession(user="kacper", uid=1234), wait=False)
        assert cmd[2] == "kacper"
        assert "XDG_RUNTIME_DIR=/run/user/1234" in cmd


class TestSettleScreenshot:
    def test_stops_after_stable_frames(self, tmp_path: Path) -> None:
        backend = FakeBackend()
        out = tmp_path / "shot.png"
        info = settle_screenshot(
            backend,
            "vm",
            out,
            waits=GuestWaits.instant(settle_min_wait=0.0, stable_frames=2, settle_interval=1.0),
        )
        assert info.settled is True
        assert info.frames == 2
        assert out.exists()
        assert len([c for c in backend.calls if c.method == "screenshot"]) == 2

    def test_respects_min_wait(self, tmp_path: Path) -> None:
        waits = GuestWaits.instant(settle_min_wait=3.0, stable_frames=2, settle_interval=1.0)
        info = settle_screenshot(FakeBackend(), "vm", tmp_path / "shot.png", waits=waits)
        assert info.settled is True
        assert info.elapsed >= 3.0
        assert info.frames == 4

    def test_changing_frames_time_out_unsettled(self, tmp_path: Path) -> None:
        class _Flicker(FakeBackend):
            def __init__(self) -> None:
                super().__init__()
                self.n = 0

            def screenshot(self, name: str, out_path: Path) -> Path:
                self.n += 1
                out_path.write_bytes(b"frame-%d" % self.n)
                return out_path

        waits = GuestWaits.instant(settle_min_wait=0.0, settle_timeout=5.0, settle_interval=1.0)
        info = settle_screenshot(_Flicker(), "vm", tmp_path / "shot.png", waits=waits)
        assert info.settled is False
        assert info.frames == 6
        assert (tmp_path / "shot.png").read_bytes() == b"frame-6"

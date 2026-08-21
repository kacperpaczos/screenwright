"""Testy jednostkowe — domains.matrix.guest: gotowość gościa, shell sesji, settle."""

from __future__ import annotations

import time
from pathlib import Path  # noqa: TC003  (tmp_path / fixtures at runtime)

import pytest
from domains.matrix.backend.fake import FakeBackend, FakeScreen, FakeShell
from domains.matrix.guest import (
    SESSION_PROBE,
    GuestWaits,
    frame_digest,
    launch,
    session_command,
    settle_screenshot,
    wait_for_agent,
    wait_for_session,
    wait_for_shell,
)


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


class TestWaitForShell:
    def test_retries_until_ssh_answers(self) -> None:
        shell = FakeShell(fail_first=2)
        wait_for_shell(shell, waits=GuestWaits.instant())
        assert shell.calls == [["true"]] * 3

    def test_times_out(self) -> None:
        shell = FakeShell(fail_first=10**6)
        waits = GuestWaits.instant(shell_timeout=4.0, probe_interval=1.0)
        with pytest.raises(TimeoutError, match=r"guest shell did not answer within 4s.*refused"):
            wait_for_shell(shell, waits=waits)


class TestWaitForSession:
    def test_probe_is_systemctl_user_is_active(self) -> None:
        assert SESSION_PROBE == ["systemctl", "--user", "is-active", "graphical-session.target"]

    def test_nonzero_exit_then_active(self) -> None:
        # systemctl is-active kończy się kodem 3 (→ RuntimeError z shella), dopóki target nie wstanie.
        shell = FakeShell(fail_first=2)
        wait_for_session(shell, waits=GuestWaits.instant())
        assert shell.calls == [SESSION_PROBE] * 3

    def test_inactive_answer_keeps_polling_then_times_out(self) -> None:
        shell = FakeShell(output={" ".join(SESSION_PROBE): "inactive\n"})
        waits = GuestWaits.instant(session_timeout=3.0, probe_interval=1.0)
        with pytest.raises(TimeoutError, match=r"not active after 3s.*'inactive'"):
            wait_for_session(shell, waits=waits)


class TestSessionCommand:
    def test_wraps_argv_in_detached_user_unit(self) -> None:
        cmd = session_command(["plasma-discover", "--application=appstream:x"], wait=False)
        assert cmd == [
            "systemd-run",
            "--user",
            "--collect",
            "--quiet",
            "--",
            "plasma-discover",
            "--application=appstream:x",
        ]

    def test_wait_flag_blocks_until_exit(self) -> None:
        cmd = session_command(["gnome-software", "--quit"], wait=True)
        assert cmd == [
            "systemd-run",
            "--user",
            "--collect",
            "--quiet",
            "--wait",
            "--",
            "gnome-software",
            "--quit",
        ]


class TestLaunch:
    def test_all_but_last_command_wait(self) -> None:
        shell = FakeShell()
        launch(
            shell,
            [["store", "--quit"], ["store", "--refresh"], ["store", "--details=x"]],
            waits=GuestWaits.instant(),
        )
        assert ["--wait" in c for c in shell.calls] == [True, True, False]
        assert [c[-1] for c in shell.calls] == ["--quit", "--refresh", "--details=x"]

    def test_failing_command_propagates(self) -> None:
        shell = FakeShell(raise_on_command={"broken-store"})
        with pytest.raises(RuntimeError, match="exit=127"):
            launch(shell, [["broken-store"]], waits=GuestWaits.instant())

    def test_detached_launch_changes_shared_screen(self) -> None:
        screen = FakeScreen()
        shell = FakeShell(screen=screen)
        launch(shell, [["store", "--quit"], ["store", "--details=x"]], waits=GuestWaits.instant())
        assert screen.generation == 1  # tylko odczepiona komenda „rysuje"


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
        assert info.changed is True  # bez punktu odniesienia każda klatka „się zmieniła"
        assert info.frames == 2
        assert out.exists()
        assert len([c for c in backend.calls if c.method == "screenshot"]) == 2

    def test_respects_min_wait(self, tmp_path: Path) -> None:
        waits = GuestWaits.instant(settle_min_wait=3.0, stable_frames=2, settle_interval=1.0)
        info = settle_screenshot(FakeBackend(), "vm", tmp_path / "shot.png", waits=waits)
        assert info.settled is True
        assert info.elapsed >= 3.0
        assert info.frames == 4

    def test_unchanged_screen_is_not_settled(self, tmp_path: Path) -> None:
        """Stabilny pulpit ≠ wyrenderowany sklep: bez zmiany względem baseline czekamy do limitu."""
        backend = FakeBackend()
        out = tmp_path / "shot.png"
        baseline = frame_digest(backend, "vm", out)
        waits = GuestWaits.instant(settle_min_wait=0.0, settle_timeout=5.0, settle_interval=1.0)
        info = settle_screenshot(backend, "vm", out, waits=waits, baseline=baseline)
        assert info.settled is False
        assert info.changed is False
        assert info.frames == 6

    def test_settles_once_screen_changed_and_holds(self, tmp_path: Path) -> None:
        screen = FakeScreen()
        backend = FakeBackend(screen=screen)
        out = tmp_path / "shot.png"
        baseline = frame_digest(backend, "vm", out)
        screen.bump()  # sklep się narysował
        waits = GuestWaits.instant(settle_min_wait=0.0, stable_frames=2, settle_interval=1.0)
        info = settle_screenshot(backend, "vm", out, waits=waits, baseline=baseline)
        assert info.settled is True
        assert info.changed is True
        assert info.frames == 2

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
        assert info.changed is True
        assert info.frames == 6
        assert (tmp_path / "shot.png").read_bytes() == b"frame-6"

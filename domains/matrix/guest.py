"""Gotowość gościa i uruchamianie komend w jego sesji graficznej.

Drivery sklepów opisują komendy GUI, które mają się narysować na pulpicie
autologowanego użytkownika i nigdy się nie kończą. ``qemu-guest-agent`` nie
nadaje się do ich odpalania: działa jako root w domenie SELinux
``virt_qemu_ga_t``, która nie może zmienić użytkownika (``runuser``, ``setpriv``:
„Operation not permitted") ani zagadać do systemd (``systemd-run``: „Access
denied") — sprawdzone na Fedorze 44, 2026-08-22. Dlatego:

- ``wait_for_agent`` — agent służy tylko za „gość żyje" (``guest-exec true``)
  i za kanał do ``virsh screenshot``;
- ``wait_for_shell`` / ``wait_for_session`` — komendy w sesji idą przez
  ``GuestShell`` (na żywo SSH jako użytkownik sesji, przez przekierowany port
  passt): najpierw czekamy, aż SSH odpowiada, potem aż ``graphical-session.target``
  użytkownika jest ``active`` (kompozytor już rysuje);
- ``session_command`` / ``launch`` — każde argv owinięte w ``systemd-run --user
  --collect --quiet [--wait] -- …``: proces startuje w managerze użytkownika
  (GNOME i Plasma importują tam DISPLAY/WAYLAND_DISPLAY/DBUS), a bez ``--wait``
  ``systemd-run`` odczepia go, więc wywołanie wraca od razu;
- ``settle_screenshot`` — zrzut dopiero wtedy, gdy kolejne klatki przestają się
  różnić **i** różnią się od klatki sprzed uruchomienia (stabilny pulpit to nie
  jest wyrenderowany sklep). Ta sama pętla, co w ``domains/capture/run.py``,
  której nie wolno stąd importować — granice domen.

Czekanie idzie przez ``GuestWaits`` z wstrzykiwanym zegarem: w trybie testowym
(``SCREENWRIGHT_TESTS_FAST``) ``sleep`` tylko przesuwa sztuczny zegar, więc
pętle kończą się natychmiast, a logika timeoutów jest nadal sprawdzalna.
"""

from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING

from shared.logging import log_entry
from shared.pydantic_utils import is_test_mode

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from shared.ports import LibvirtBackend

    from domains.matrix.ports import GuestShell

SESSION_PROBE = ["systemctl", "--user", "is-active", "graphical-session.target"]
"""Komenda (jako użytkownik sesji) mówiąca, czy sesja graficzna już działa."""


class FakeClock:
    """Zegar testowy: ``sleep()`` przesuwa czas, nikt naprawdę nie czeka."""

    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += max(0.0, seconds)


@dataclass(frozen=True)
class GuestWaits:
    """Limity i odstępy czekania na gościa + źródło czasu.

    Wartości domyślne są pod zimny boot pełnego desktopu na 2 vCPU; warm
    restore kończy się w pierwszej próbie, więc tych samych limitów można użyć
    bez zmian.
    """

    agent_timeout: float = 180.0
    shell_timeout: float = 120.0
    session_timeout: float = 120.0
    probe_interval: float = 1.0
    probe_timeout: float = 20.0
    launch_timeout: float = 60.0
    settle_min_wait: float = 3.0
    settle_timeout: float = 120.0
    settle_interval: float = 1.0
    stable_frames: int = 2
    clock: Callable[[], float] = time.monotonic
    sleep: Callable[[float], None] = time.sleep

    @classmethod
    def default(cls) -> GuestWaits:
        """Prawdziwy zegar, chyba że ``SCREENWRIGHT_TESTS_FAST`` — wtedy natychmiastowy."""
        return cls.instant() if is_test_mode() else cls()

    @classmethod
    def instant(cls, **overrides: float | int) -> GuestWaits:
        clock = FakeClock()
        return cls(clock=clock, sleep=clock.sleep, **overrides)  # type: ignore[arg-type]


@dataclass(frozen=True)
class SettleInfo:
    frames: int
    settled: bool
    changed: bool
    elapsed: float


def wait_for_agent(backend: LibvirtBackend, name: str, *, waits: GuestWaits) -> None:
    """Czeka, aż ``guest-exec true`` przejdzie — dopóki agent nie wstanie, virsh rzuca."""
    deadline = waits.clock() + waits.agent_timeout
    last_error: Exception | None = None
    while True:
        try:
            backend.qemu_agent_exec(name, ["true"], timeout=waits.probe_timeout)
            return
        except (
            Exception
        ) as exc:  # RuntimeError, TimeoutExpired, TimeoutError — agent jeszcze nie wstał
            last_error = exc
        if waits.clock() >= deadline:
            raise TimeoutError(
                f"guest agent in {name} did not answer within {waits.agent_timeout:g}s: {last_error}"
            )
        waits.sleep(waits.probe_interval)


def wait_for_shell(shell: GuestShell, *, waits: GuestWaits) -> None:
    """Czeka, aż ``shell.run(["true"])`` przejdzie — sshd, passt i klucz muszą się zgrać."""
    deadline = waits.clock() + waits.shell_timeout
    last_error: Exception | None = None
    while True:
        try:
            shell.run(["true"], timeout=waits.probe_timeout)
            return
        except Exception as exc:  # connection refused / timeout — gość jeszcze nie nasłuchuje
            last_error = exc
        if waits.clock() >= deadline:
            raise TimeoutError(
                f"guest shell did not answer within {waits.shell_timeout:g}s: {last_error}"
            )
        waits.sleep(waits.probe_interval)


def wait_for_session(shell: GuestShell, *, waits: GuestWaits) -> None:
    """Czeka na ``graphical-session.target`` = ``active`` u użytkownika sesji.

    ``systemctl is-active`` kończy się kodem 3, gdy target nie jest aktywny, a
    shell zamienia niezerowy kod na wyjątek — stąd próba jest udana tylko
    wtedy, gdy nie rzuciła **i** wypisała ``active``.
    """
    deadline = waits.clock() + waits.session_timeout
    last = ""
    while True:
        try:
            last = shell.run(SESSION_PROBE, timeout=waits.probe_timeout).strip()
        except Exception as exc:  # niezerowy kod systemctl → RuntimeError z shella
            last = f"error: {exc}"
        if last == "active":
            return
        if waits.clock() >= deadline:
            raise TimeoutError(
                f"graphical session not active after {waits.session_timeout:g}s "
                f"(last answer: {last!r})"
            )
        waits.sleep(waits.probe_interval)


def session_command(cmd: list[str], *, wait: bool) -> list[str]:
    """Owija argv tak, by ruszył w managerze użytkownika i nie blokował wywołującego.

    ``wait=True`` każe ``systemd-run`` poczekać na koniec komendy — dla kroków
    pomocniczych (``gnome-software --quit``), które mają skończyć się przed
    następnym. Komenda otwierająca stronę aplikacji idzie bez ``--wait``, bo
    proces GUI nigdy nie kończy się sam.
    """
    unit = ["systemd-run", "--user", "--collect", "--quiet"]
    if wait:
        unit.append("--wait")
    return [*unit, "--", *cmd]


def launch(shell: GuestShell, commands: list[list[str]], *, waits: GuestWaits) -> None:
    """Komendy drivera w sesji użytkownika: wszystkie poza ostatnią z ``--wait``.

    Ostatnia otwiera stronę aplikacji i zostaje na ekranie — na nią czeka
    już ``settle_screenshot``, nie ``systemd-run``.
    """
    last = len(commands) - 1
    for index, cmd in enumerate(commands):
        shell.run(session_command(cmd, wait=index < last), timeout=waits.launch_timeout)


def frame_digest(backend: LibvirtBackend, name: str, out_path: Path) -> str:
    """Jedna klatka ekranu + jej skrót — punkt odniesienia dla ``settle_screenshot``."""
    backend.screenshot(name, out_path)
    return hashlib.sha256(out_path.read_bytes()).hexdigest()


def settle_screenshot(
    backend: LibvirtBackend,
    name: str,
    out_path: Path,
    *,
    waits: GuestWaits,
    baseline: str | None = None,
) -> SettleInfo:
    """Robi zrzuty, aż ``stable_frames`` kolejnych klatek jest identycznych.

    Z ``baseline`` (skrót klatki sprzed uruchomienia sklepu) klatki równe
    punktowi odniesienia nie liczą się jako ustabilizowane — ekran, który się
    nie zmienił, to sklep, który się jeszcze nie narysował. Ostatnia klatka
    zostaje w ``out_path``; po ``settle_timeout`` oddajemy, co mamy, z
    ``settled=False`` (zrzut jest lepszy niż brak dowodu).
    """
    started = waits.clock()
    previous: str | None = None
    repeats = 0
    frames = 0
    changed = baseline is None
    while True:
        backend.screenshot(name, out_path)
        frames += 1
        digest = hashlib.sha256(out_path.read_bytes()).hexdigest()
        if digest != baseline:
            changed = True
        repeats = repeats + 1 if digest == previous else 1
        previous = digest
        elapsed = waits.clock() - started
        if changed and repeats >= waits.stable_frames and elapsed >= waits.settle_min_wait:
            return SettleInfo(frames=frames, settled=True, changed=True, elapsed=elapsed)
        if elapsed >= waits.settle_timeout:
            log_entry(
                30,
                "matrix.guest.not_settled",
                domain=name,
                frames=frames,
                changed=changed,
                elapsed=elapsed,
            )
            return SettleInfo(frames=frames, settled=False, changed=changed, elapsed=elapsed)
        waits.sleep(waits.settle_interval)


__all__ = [
    "SESSION_PROBE",
    "FakeClock",
    "GuestWaits",
    "SettleInfo",
    "frame_digest",
    "launch",
    "session_command",
    "settle_screenshot",
    "wait_for_agent",
    "wait_for_session",
    "wait_for_shell",
]

"""Gotowość gościa i uruchamianie komend w jego sesji graficznej.

`qemu-guest-agent` wykonuje komendy jako root, bez `DISPLAY`, bez szyny sesji
i bez czekania na cokolwiek — a drivery sklepów opisują komendy GUI, które
mają się narysować na pulpicie autologowanego użytkownika i nigdy się nie
kończą. Ten moduł łata obie różnice:

- ``wait_for_agent`` / ``wait_for_session`` — zanim cokolwiek ruszy, agent
  musi odpowiadać, a ``graphical-session.target`` użytkownika musi być
  ``active`` (to jest moment, w którym kompozytor już rysuje);
- ``session_command`` — owija argv w ``runuser -u <user> -- env
  XDG_RUNTIME_DIR=… systemd-run --user …``: proces startuje w managerze
  użytkownika (GNOME i Plasma importują tam DISPLAY/WAYLAND_DISPLAY/DBUS),
  a ``systemd-run`` odczepia go, więc ``guest-exec`` wraca od razu;
- ``settle_screenshot`` — zrzut dopiero wtedy, gdy kolejne klatki przestają
  się różnić (ta sama pętla, co w ``domains/capture/run.py``, której nie wolno
  stąd importować — granice domen).

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
    session_timeout: float = 120.0
    probe_interval: float = 1.0
    probe_timeout: float = 10.0
    settle_min_wait: float = 3.0
    settle_timeout: float = 30.0
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
class GuestSession:
    """Użytkownik sesji graficznej w gościu i jego ``XDG_RUNTIME_DIR``."""

    user: str
    uid: int

    @property
    def runtime_dir(self) -> str:
        return f"/run/user/{self.uid}"


@dataclass(frozen=True)
class SettleInfo:
    frames: int
    settled: bool
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


def resolve_session(
    backend: LibvirtBackend, name: str, user: str, *, waits: GuestWaits
) -> GuestSession:
    """``id -u <user>`` w gościu — uid potrzebny do ``/run/user/<uid>``."""
    out = backend.qemu_agent_exec(name, ["id", "-u", user], timeout=waits.probe_timeout)
    try:
        uid = int(out.strip())
    except ValueError as exc:
        raise RuntimeError(f"cannot resolve uid of {user!r} in {name}: {out!r}") from exc
    return GuestSession(user=user, uid=uid)


def session_probe(session: GuestSession) -> list[str]:
    """Komenda sprawdzająca, czy sesja graficzna użytkownika już działa."""
    return _as_user(session, ["systemctl", "--user", "is-active", "graphical-session.target"])


def wait_for_session(
    backend: LibvirtBackend, name: str, session: GuestSession, *, waits: GuestWaits
) -> None:
    """Czeka na ``graphical-session.target`` = ``active`` u użytkownika sesji.

    ``systemctl is-active`` kończy się kodem 3, gdy target nie jest aktywny, a
    backend zamienia niezerowy kod na wyjątek — stąd próba jest udana tylko
    wtedy, gdy nie rzuciła **i** wypisała ``active``.
    """
    deadline = waits.clock() + waits.session_timeout
    probe = session_probe(session)
    last: str = ""
    while True:
        try:
            last = backend.qemu_agent_exec(name, probe, timeout=waits.probe_timeout).strip()
        except Exception as exc:  # niezerowy kod systemctl → RuntimeError z backendu
            last = f"error: {exc}"
        if last == "active":
            return
        if waits.clock() >= deadline:
            raise TimeoutError(
                f"graphical session of {session.user!r} in {name} not active after "
                f"{waits.session_timeout:g}s (last answer: {last!r})"
            )
        waits.sleep(waits.probe_interval)


def session_command(cmd: list[str], session: GuestSession, *, wait: bool) -> list[str]:
    """Owija argv tak, by ruszył w sesji graficznej użytkownika i nie blokował agenta.

    ``wait=True`` każe ``systemd-run`` poczekać na koniec komendy — dla kroków
    pomocniczych (``gnome-software --quit``), które mają skończyć się przed
    następnym. Komenda otwierająca stronę aplikacji idzie bez ``--wait``, bo
    proces GUI nigdy nie kończy się sam.
    """
    unit = ["systemd-run", "--user", "--collect", "--quiet"]
    if wait:
        unit.append("--wait")
    return _as_user(session, [*unit, "--", *cmd])


def _as_user(session: GuestSession, cmd: list[str]) -> list[str]:
    """``runuser`` zamiast ``su``/``sudo``: bez PAM-owej sesji, bez hasła, jako root z agenta."""
    runtime_dir = session.runtime_dir
    return [
        "runuser",
        "-u",
        session.user,
        "--",
        "env",
        f"XDG_RUNTIME_DIR={runtime_dir}",
        f"DBUS_SESSION_BUS_ADDRESS=unix:path={runtime_dir}/bus",
        *cmd,
    ]


def settle_screenshot(
    backend: LibvirtBackend, name: str, out_path: Path, *, waits: GuestWaits
) -> SettleInfo:
    """Robi zrzuty, aż ``stable_frames`` kolejnych klatek jest identycznych.

    Ostatnia klatka zostaje w ``out_path`` — to jest zrzut do porównania.
    Po ``settle_timeout`` oddajemy, co mamy, z ``settled=False`` (migający
    kursor potrafi nigdy nie dać dwóch równych klatek); zrzut jest i tak
    lepszy niż brak dowodu.
    """
    started = waits.clock()
    previous: str | None = None
    repeats = 0
    frames = 0
    while True:
        backend.screenshot(name, out_path)
        frames += 1
        digest = hashlib.sha256(out_path.read_bytes()).hexdigest()
        repeats = repeats + 1 if digest == previous else 1
        previous = digest
        elapsed = waits.clock() - started
        if repeats >= waits.stable_frames and elapsed >= waits.settle_min_wait:
            return SettleInfo(frames=frames, settled=True, elapsed=elapsed)
        if elapsed >= waits.settle_timeout:
            log_entry(30, "matrix.guest.not_settled", domain=name, frames=frames, elapsed=elapsed)
            return SettleInfo(frames=frames, settled=False, elapsed=elapsed)
        waits.sleep(waits.settle_interval)


__all__ = [
    "FakeClock",
    "GuestSession",
    "GuestWaits",
    "SettleInfo",
    "resolve_session",
    "session_command",
    "session_probe",
    "settle_screenshot",
    "wait_for_agent",
    "wait_for_session",
]

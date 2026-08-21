"""Runner domeny matrix — plan() i execute()."""

from __future__ import annotations

import shutil
import socket
import time
from contextlib import ExitStack, contextmanager, suppress
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

from shared.logging import log_entry
from shared.results import MatrixReport, PhaseTiming, Score, VerificationResult

if TYPE_CHECKING:
    from shared.ports import LibvirtBackend

from domains.matrix.backend.fake import FakeBackend, make_unique_name
from domains.matrix.backend.ssh import ssh_shell_for
from domains.matrix.domain_xml import render_domain_xml
from domains.matrix.guest import (
    Frame,
    GuestWaits,
    capture_frame,
    launch,
    settle_screenshot,
    wait_for_agent,
    wait_for_session,
    wait_for_shell,
    window_probe_for,
)
from domains.matrix.models import (
    _MATRIX_STEP_VERBS,
    DEFAULT_DOMAIN,
    DistroName,
    DistroSpec,
    DomainConfig,
    MatrixRunSpec,
    MatrixStep,
)
from domains.matrix.warm_cache import (
    DISK_NAME,
    STATE_NAME,
    WarmCache,
    WarmTemplate,
    hardware_of,
    template_name,
)

if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator

    from shared.types import AppId

    from domains.matrix.ports import (
        GuestShell,
        GuestShellFactory,
        ReporterSink,
        StoreDriver,
        StoreProxyLifecycle,
        StoreProxyProvider,
    )


@runtime_checkable
class TemplateMatcherPort(Protocol):
    threshold: Score

    def match(self, template: Path, actual: Path) -> Score: ...


def _default_matcher(threshold: float = 0.85) -> TemplateMatcherPort:
    threshold_score = Score(value=threshold)

    class _Default:
        threshold = threshold_score

        def match(self, template: Path, actual: Path) -> Score:
            if not template.exists() or not actual.exists():
                return Score(value=0.0)
            if template.read_bytes() == actual.read_bytes():
                return Score(value=1.0)
            return Score(value=0.0)

    return _Default()


def plan(spec: MatrixRunSpec) -> list[MatrixStep]:
    """Zwraca listę kroków (MatrixStep) — wykonanie tylko przez execute()."""
    steps: list[MatrixStep] = []
    seq = 0
    for distro in spec.distros:
        seq = _plan_distro(steps, seq, distro.name, distro.name.value, spec)
        for app in spec.apps:
            for verb in _app_verbs_for_run():
                steps.append(
                    MatrixStep.new(
                        sequence=seq,
                        distro=distro.name,
                        app=app,
                        verb=verb,
                        args={"batch_size": spec.batch, "dry_run": spec.dry_run},
                    )
                )
                seq += 1
    return steps


def _plan_distro(
    steps: list[MatrixStep],
    seq: int,
    distro: DistroName,
    distro_label: str,
    spec: MatrixRunSpec,
) -> int:
    """Kroki boot/destroy per dystrybucja (bezpośrednio przed app-specific)."""
    for verb in _distro_verbs_for_run():
        steps.append(
            MatrixStep.new(
                sequence=seq,
                distro=distro,
                app=distro_label,
                verb=verb,
                args={"batch_size": spec.batch, "dry_run": spec.dry_run},
            )
        )
        seq += 1
    return seq


def execute(
    spec: MatrixRunSpec,
    *,
    backend: LibvirtBackend | None = None,
    drivers: dict[DistroName, StoreDriver] | None = None,
    matcher: TemplateMatcherPort | None = None,
    reporter: ReporterSink | None = None,
    work_root: Path = Path("/tmp/screenwright-matrix"),
    store_proxy_provider: StoreProxyProvider | None = None,
    waits: GuestWaits | None = None,
    shell_factory: GuestShellFactory | None = None,
    warm_root: Path | None = None,
    cache_key: str = "",
) -> MatrixReport:
    """Wykonuje przebieg matrycy. W trybie dry_run NIE wywołuje backendu.

    Pętla per-dystrybucja: jedna domena bootuje się raz, wszystkie apps z
    listy sprawdzane są w tej samej VM (store przełączany przez driver).
    Ciepły start w obrębie przebiegu jest darmowy; save/restore jest
    capability backendu (do optymalizacji między przebiegami).

    ``store_proxy_provider`` jest wywoływany per-dystrybucja; jeśli zwróci
    obiekt ``StoreProxyLifecycle``, runner wywołuje ``start()`` przed pętlą
    po apps i ``stop()`` po (również przy wyjątkach). W ``dry_run`` provider
    nie jest używany — pętla mockuje brak proxy.

    Po ``create`` runner czeka na agenta, na shell w gościu i na sesję
    graficzną ``DistroSpec.guest_user`` (``domains.matrix.guest``), komendy
    drivera odpala przez ``GuestShell`` w tej sesji, a zrzut robi dopiero,
    gdy ekran zmienił się względem klatki sprzed uruchomienia i przestał się
    zmieniać. ``waits`` steruje limitami (``None`` = ``GuestWaits.default()``);
    ``shell_factory`` buduje shell per klon (``None`` = SSH przez port passt).

    ``warm_root`` włącza warm cache (``domains.matrix.warm_cache``): trafienie
    w szablon to ``restore`` zamiast bootu; chybienie — zimny boot do gotowości,
    ``save`` i od razu ``restore`` z nowego szablonu; nieudany ``restore`` —
    głośny fallback na zimny boot. ``cache_key`` (np. wersja QEMU) unieważnia
    szablony po upgrade'ach hosta.
    """
    if backend is None:
        backend = FakeBackend()
    if waits is None:
        waits = GuestWaits.default()
    if shell_factory is None:
        shell_factory = ssh_shell_for
    if matcher is None:
        matcher = _build_matcher(spec.verify_threshold)
    started_at = datetime.now(UTC)
    run_id = make_unique_name("run")
    results: list[VerificationResult] = []
    timings: list[PhaseTiming] = []

    if not spec.dry_run:
        work_root.mkdir(parents=True, exist_ok=True)
    warm_cache = WarmCache(warm_root, cache_key=cache_key) if warm_root is not None else None

    for distro in spec.distros:
        distro_label = distro.name.value
        _hardware_for(distro)  # waliduje domain_overrides także w dry_run — błąd ma wyjść od razu
        with ExitStack() as stack:
            proxy: StoreProxyLifecycle | None = None
            if not spec.dry_run and store_proxy_provider is not None:
                proxy = store_proxy_provider(distro, spec.apps)
                if proxy is not None:
                    with _timed(timings, distro_label, None, "proxy_start"):
                        _start_store_proxy(proxy, distro.name)

            warm_here: WarmCache | None = None
            if warm_cache is not None and not spec.dry_run:
                if stack.enter_context(warm_cache.lock(distro.name)):
                    warm_here = warm_cache
                else:
                    log_entry(30, "matrix.warm.busy", distro=distro_label)

            driver = (drivers or {}).get(distro.name)
            probe_cmd = driver.window_probe() if driver is not None else None
            clone: _Clone | None = None
            if not spec.dry_run:
                clone = _bring_up(
                    backend,
                    shell_factory,
                    distro,
                    work_root=work_root,
                    warm_cache=warm_here,
                    warmup=driver.warmup_commands() if driver is not None else [],
                    window_probe=probe_cmd,
                    waits=waits,
                    timings=timings,
                )
            window_present = (
                window_probe_for(clone.shell, probe_cmd, waits=waits)
                if clone is not None and probe_cmd is not None
                else None
            )

            try:
                for app in spec.apps:
                    actual = (
                        work_root / f"{clone.name}-{app}.png"
                        if clone is not None
                        else Path("/tmp/dry.png")
                    )
                    if clone is not None:
                        baseline: Frame | None = None
                        if driver is not None:
                            with _timed(timings, distro_label, app, "launch") as detail:
                                commands = driver.commands_for(app)
                                detail["commands"] = len(commands)
                                if commands:
                                    baseline = capture_frame(backend, clone.name, actual)
                                    launch(clone.shell, commands, waits=waits)
                        with _timed(timings, distro_label, app, "settle") as detail:
                            settled = settle_screenshot(
                                backend,
                                clone.name,
                                actual,
                                waits=waits,
                                baseline=baseline,
                                window_present=window_present,
                            )
                            detail["frames"] = settled.frames
                            detail["settled"] = settled.settled
                            detail["changed"] = settled.changed
                            detail["distance"] = round(settled.distance, 4)
                            detail["window"] = settled.window
                    template = _resolve_template(spec.templates_dir, distro.name, app)
                    with _timed(timings, distro_label, app, "verify"):
                        score = matcher.match(template, actual)
                    passed = score.value >= matcher.threshold.value
                    result = VerificationResult(
                        passed=passed,
                        score=score,
                        threshold=matcher.threshold,
                        location=(0, 0),
                        expected_template=template,
                        actual_screenshot=actual,
                        notes=(
                            "dry_run: template same as actual; identity-matcher returns 1.0"
                            if spec.dry_run
                            else None
                        ),
                    )
                    results.append(result)
                    if reporter is not None:
                        reporter.record(result.model_dump(mode="json"))
            finally:
                if clone is not None:
                    with _timed(timings, distro_label, None, "teardown"):
                        _teardown(backend, clone.name, clone.disk_path)
                if proxy is not None:
                    proxy.stop()

    return MatrixReport(
        run_id=run_id,
        started_at=started_at,
        finished_at=datetime.now(UTC),
        results=results,
        timings=timings,
    )


@contextmanager
def _timed(
    timings: list[PhaseTiming],
    distro: str,
    app: AppId | None,
    phase: str,
) -> Iterator[dict[str, str | int | float | bool | None]]:
    """Mierzy jedną fazę i dopisuje `PhaseTiming` do `timings` — także po wyjątku.

    Yielduje słownik `detail`, do którego faza może dopisać liczby (ile komend,
    ile klatek). `ok` ustawiamy sami: porażka po 60 s czekania i porażka po
    0.1 s to dwie różne diagnozy, więc czas nie może przepaść razem z wyjątkiem.
    """
    detail: dict[str, str | int | float | bool | None] = {}
    started_at = datetime.now(UTC)
    t0 = time.perf_counter()
    ok = True
    try:
        yield detail
    except BaseException:
        ok = False
        raise
    finally:
        timings.append(
            PhaseTiming(
                distro=distro,
                app=str(app) if app is not None else None,
                phase=phase,
                started_at=started_at,
                seconds=time.perf_counter() - t0,
                detail={**detail, "ok": ok},
            )
        )


@dataclass(frozen=True)
class _Clone:
    """Działający, gotowy klon: nazwa domeny, jego overlay i shell do sesji."""

    name: str
    disk_path: Path
    shell: GuestShell


def _hardware_for(distro: DistroSpec) -> dict[str, Any]:
    """Sprzęt klona z ``DEFAULT_DOMAIN`` + ``domain_overrides`` — klucz zgodności szablonu warm."""
    return hardware_of(_domain_for(distro, name="sw-hardware-probe", ssh_port=2222))


def _wait_ready(
    backend: LibvirtBackend,
    shell: GuestShell,
    name: str,
    *,
    waits: GuestWaits,
    timings: list[PhaseTiming],
    label: str,
) -> None:
    with _timed(timings, label, None, "wait_agent"):
        wait_for_agent(backend, name, waits=waits)
    with _timed(timings, label, None, "wait_shell"):
        wait_for_shell(shell, waits=waits)
    with _timed(timings, label, None, "wait_session"):
        wait_for_session(shell, waits=waits)


def _cold_clone(
    backend: LibvirtBackend,
    shell_factory: GuestShellFactory,
    distro: DistroSpec,
    domain: DomainConfig,
    xml: str,
    disk_path: Path,
    *,
    waits: GuestWaits,
    timings: list[PhaseTiming],
    warm: str,
) -> _Clone:
    """Overlay na golden → ``virsh create`` → gotowość. Gdy gotowość padnie, sprząta i rzuca dalej."""
    label = distro.name.value
    with _timed(timings, label, None, "create_overlay"):
        backend.create_overlay(distro.golden_image, disk_path)
    with _timed(timings, label, None, "create") as detail:
        detail["warm"] = warm
        backend.create(xml, domain.name)
    shell = shell_factory(domain, distro)
    try:
        _wait_ready(backend, shell, domain.name, waits=waits, timings=timings, label=label)
    except BaseException:
        _teardown(backend, domain.name, disk_path)
        raise
    return _Clone(name=domain.name, disk_path=disk_path, shell=shell)


def _plain_cold(
    backend: LibvirtBackend,
    shell_factory: GuestShellFactory,
    distro: DistroSpec,
    *,
    work_root: Path,
    waits: GuestWaits,
    timings: list[PhaseTiming],
) -> _Clone:
    """Klon jak przed warm cache: unikalna nazwa, wolny port, overlay w ``work_root``."""
    name = make_unique_name(f"sw-{distro.name.value.replace('.', '-')}")
    domain = _domain_for(distro, name=name, ssh_port=pick_ssh_port())
    disk_path = _disk_path(work_root, distro.name)
    xml = render_domain_xml(domain, disk_path, cdrom_path=distro.seed_iso)
    return _cold_clone(
        backend,
        shell_factory,
        distro,
        domain,
        xml,
        disk_path,
        waits=waits,
        timings=timings,
        warm="off",
    )


def _restore_template(
    backend: LibvirtBackend,
    shell_factory: GuestShellFactory,
    distro: DistroSpec,
    template: WarmTemplate,
    warm_cache: WarmCache,
    *,
    waits: GuestWaits,
    timings: list[PhaseTiming],
) -> _Clone | None:
    """Świeży overlay na ``base`` + ``restore --xml`` + gotowość; ``None`` = szablon do wyrzucenia."""
    label = distro.name.value
    name = template.manifest.name
    domain = _domain_for(distro, name=name, ssh_port=template.manifest.ssh_port)
    try:
        with suppress(
            Exception
        ):  # niedobitek po przerwanym przebiegu; brak domeny to stan oczekiwany
            backend.destroy(name)
        with _timed(timings, label, None, "create_overlay"):
            backend.create_overlay(template.base, template.disk)
        with _timed(timings, label, None, "warm_restore") as detail:
            detail["warm"] = "hit"
            backend.restore(template.state, xml=template.xml)
        shell = shell_factory(domain, distro)
        _wait_ready(backend, shell, name, waits=waits, timings=timings, label=label)
    except Exception as exc:
        log_entry(30, "matrix.warm.restore_failed", distro=label, error=str(exc))
        _teardown(backend, name, template.disk)
        warm_cache.invalidate(distro.name)
        return None
    return _Clone(name=name, disk_path=template.disk, shell=shell)


def _build_template(
    backend: LibvirtBackend,
    shell_factory: GuestShellFactory,
    distro: DistroSpec,
    warm_cache: WarmCache,
    *,
    work_root: Path,
    warmup: list[list[str]],
    window_probe: list[str] | None,
    waits: GuestWaits,
    timings: list[PhaseTiming],
) -> _Clone:
    """Zimny boot na dysku szablonu → rozgrzewka sklepu → ``save`` → zamrożenie → ``restore``.

    ``warmup`` (``StoreDriver.warmup_commands()``) stawia sklep na ekranie
    głównym i czekamy, aż się narysuje, zanim zapiszemy stan — po restore każda
    aplikacja to nawigacja w działającym sklepie, nie zimny start.
    ``save`` gasi domenę, więc przebieg i tak musi przejść przez ``restore`` —
    dzięki temu pierwszy przebieg sprawdza tę samą ścieżkę, co każdy następny.
    Gdy ``save`` nie wyjdzie, jedziemy dalej na działającym zimnym klonie bez
    szablonu; gdy ``restore`` zaraz po ``save`` padnie, bootujemy jeszcze raz po
    staremu — w obu wypadkach głośno w logu, nigdy cicho.
    """
    label = distro.name.value
    name = template_name(distro.name)
    domain = _domain_for(distro, name=name, ssh_port=pick_ssh_port())
    directory = warm_cache.directory(distro.name)
    disk_path = directory / DISK_NAME
    xml = render_domain_xml(domain, disk_path, cdrom_path=distro.seed_iso)
    with suppress(Exception):  # niedobitek po przerwanym przebiegu
        backend.destroy(name)
    warm_cache.prepare(distro.name, xml)
    clone = _cold_clone(
        backend,
        shell_factory,
        distro,
        domain,
        xml,
        disk_path,
        waits=waits,
        timings=timings,
        warm="build",
    )
    try:
        with _timed(timings, label, None, "warm_save") as detail:
            ready_png = directory / "ready.png"
            baseline: Frame | None = None
            present = None
            if warmup:
                baseline = capture_frame(backend, name, ready_png)
                launch(clone.shell, warmup, waits=waits)
                if window_probe is not None:
                    present = window_probe_for(clone.shell, window_probe, waits=waits)
            quiet = settle_screenshot(
                backend, name, ready_png, waits=waits, baseline=baseline, window_present=present
            )
            detail["warmup"] = len(warmup)
            detail["settled"] = quiet.settled
            detail["changed"] = quiet.changed
            detail["window"] = quiet.window
            backend.save(name, directory / STATE_NAME)
    except Exception as exc:
        log_entry(30, "matrix.warm.save_failed", distro=label, error=str(exc))
        (directory / STATE_NAME).unlink(missing_ok=True)
        return clone
    template = warm_cache.commit(
        distro, name=name, ssh_port=domain.ssh_port, hardware=hardware_of(domain)
    )
    restored = _restore_template(
        backend, shell_factory, distro, template, warm_cache, waits=waits, timings=timings
    )
    if restored is not None:
        return restored
    log_entry(30, "matrix.warm.build_unusable", distro=label)
    return _plain_cold(
        backend, shell_factory, distro, work_root=work_root, waits=waits, timings=timings
    )


def _bring_up(
    backend: LibvirtBackend,
    shell_factory: GuestShellFactory,
    distro: DistroSpec,
    *,
    work_root: Path,
    warm_cache: WarmCache | None,
    warmup: list[list[str]],
    window_probe: list[str] | None,
    waits: GuestWaits,
    timings: list[PhaseTiming],
) -> _Clone:
    """Gotowy klon: z szablonu warm (hit), po zbudowaniu szablonu (miss) albo po staremu (bez warm)."""
    if warm_cache is not None:
        template = warm_cache.lookup(distro, _hardware_for(distro))
        if template is not None:
            clone = _restore_template(
                backend, shell_factory, distro, template, warm_cache, waits=waits, timings=timings
            )
            if clone is not None:
                return clone
        return _build_template(
            backend,
            shell_factory,
            distro,
            warm_cache,
            work_root=work_root,
            warmup=warmup,
            window_probe=window_probe,
            waits=waits,
            timings=timings,
        )
    return _plain_cold(
        backend, shell_factory, distro, work_root=work_root, waits=waits, timings=timings
    )


STORE_PROXY_READY_TIMEOUT = 20.0
"""Ile czekać, aż proxy sklepu odpowie na health-check, zanim uznamy przebieg za niewykonalny."""


def _start_store_proxy(proxy: StoreProxyLifecycle, distro: DistroName) -> None:
    """Start + czekanie na gotowość. Wołane PRZED tworzeniem overlaya i domeny.

    Jeśli proxy nie wstanie, gasimy je i rzucamy — nie ma sensu bootować VM-ki
    pod test, który z założenia pójdzie w pustkę. Teardown domeny nie jest tu
    potrzebny, bo domena jeszcze nie istnieje.
    """
    proxy.start()
    if proxy.wait_ready(STORE_PROXY_READY_TIMEOUT):
        return
    proxy.stop()
    raise RuntimeError(
        f"store proxy for {distro.value} did not become ready within {STORE_PROXY_READY_TIMEOUT:g}s"
    )


def pick_ssh_port() -> int:
    """Wolny port na 127.0.0.1 pod przekierowanie SSH do gościa.

    Dwie domeny w jednym przebiegu nie mogą dostać tego samego portu —
    passt nie wstanie, a błąd wyszedłby dopiero przy starcie drugiej VM.
    """
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _teardown(backend: LibvirtBackend, name: str, disk_path: Path) -> None:
    """Znosi domenę i usuwa overlay. Wołane z `finally` — nie może rzucać.

    `destroy` może zawieść, gdy domena już nie istnieje (np. `create` padł);
    overlay usuwamy niezależnie od tego, żeby nie zostawić pliku dysku.
    """
    try:
        backend.destroy(name)
    except Exception as exc:
        log_entry(20, "matrix.destroy_failed", domain=name, error=str(exc))
    if not disk_path.exists():
        return
    try:
        if disk_path.is_dir():
            shutil.rmtree(disk_path)
        else:
            disk_path.unlink()
    except OSError as exc:
        log_entry(20, "matrix.cleanup_failed", error=str(exc))


def _build_matcher(threshold: float) -> TemplateMatcherPort:
    """Fallback matcher gdy caller nie poda własnego — Identity (1.0 dla identycznych plików).

    OpenCVTemplateMatcher jest w `domains.verification` (osobna domena) —
    nie importujemy go tutaj (naruszałoby architekturę). Caller (CLI) powinien
    skonstruować matcher i przekazać do execute().
    """
    return _default_matcher(threshold)


def _resolve_template(
    templates_dir: Path | None,
    distro: DistroName,
    app: AppId,
) -> Path:
    """Wskazuje oczekiwany template. Jeśli brak templates_dir, zwraca /dev/null
    (Identity matcher zwróci 0.0)."""
    if templates_dir is None:
        return Path("/dev/null")
    candidate = templates_dir / distro.value / f"{app}.png"
    if candidate.exists():
        return candidate
    return Path("/dev/null")


def _distro_verbs_for_run() -> Iterable[_MATRIX_STEP_VERBS]:
    """Kroki boot/destroy per dystrybucja — renderowane przed app-specific."""
    return ("create-overlay", "create", "destroy")


def _app_verbs_for_run() -> Iterable[_MATRIX_STEP_VERBS]:
    """Kroki per (distro, app) — wykonanie komend + screenshot + verify."""
    return ("qemu-agent-exec", "screenshot", "verify")


def _domain_for(distro: DistroSpec, *, name: str, ssh_port: int) -> DomainConfig:
    """Sprzęt klona: `DEFAULT_DOMAIN` nadpisany przez `DistroSpec.domain_overrides`.

    `name` i `ssh_port` zawsze nadaje runner (unikalne per klon); spec nie
    może ich podmienić — pilnuje tego walidator `DistroSpec`. Budujemy model
    od zera zamiast `model_copy(update=)`, żeby nadpisania przeszły pełną
    walidację (`memory_mib` poza zakresem wychodzi tu, nie w virsh).
    """
    return DomainConfig(
        **{**DEFAULT_DOMAIN, **distro.domain_overrides, "name": name, "ssh_port": ssh_port}
    )


def _disk_path(root: Path, distro: DistroName) -> Path:
    return root / f"{distro.value}.qcow2"


__all__ = ["TemplateMatcherPort", "execute", "plan"]

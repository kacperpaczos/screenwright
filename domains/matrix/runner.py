"""Runner domeny matrix — plan() i execute()."""

from __future__ import annotations

import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Protocol, runtime_checkable

from shared.logging import log_entry
from shared.results import MatrixReport, Score, VerificationResult

if TYPE_CHECKING:
    from shared.ports import LibvirtBackend

from domains.matrix.backend.fake import FakeBackend, make_unique_name
from domains.matrix.domain_xml import render_domain_xml
from domains.matrix.models import (
    _MATRIX_STEP_VERBS,
    DistroName,
    DomainConfig,
    MatrixRunSpec,
    MatrixStep,
)

if TYPE_CHECKING:
    from collections.abc import Iterable

    from shared.types import AppId

    from domains.matrix.ports import ReporterSink, StoreDriver


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
) -> MatrixReport:
    """Wykonuje przebieg matrycy. W trybie dry_run NIE wywołuje backendu.

    Pętla per-dystrybucja: jedna domena bootuje się raz, wszystkie apps z
    listy sprawdzane są w tej samej VM (store przełączany przez driver).
    Ciepły start w obrębie przebiegu jest darmowy; save/restore jest
    capability backendu (do optymalizacji między przebiegami).
    """
    if backend is None:
        backend = FakeBackend()
    if matcher is None:
        matcher = _build_matcher(spec.verify_threshold)
    started_at = datetime.now(UTC)
    run_id = make_unique_name("run")
    results: list[VerificationResult] = []

    if not spec.dry_run:
        work_root.mkdir(parents=True, exist_ok=True)

    for distro in spec.distros:
        name = make_unique_name(f"sw-{distro.name.value}")
        domain = _domain_for(distro.name).model_copy(update={"name": name})
        disk_path = _disk_path(work_root if not spec.dry_run else Path("/tmp/dry"), distro.name)
        xml = render_domain_xml(domain, disk_path)

        if not spec.dry_run:
            backend.create_overlay(distro.golden_image, disk_path)
            backend.create(xml, name)

        driver = (drivers or {}).get(distro.name)
        try:
            for app in spec.apps:
                actual = (
                    work_root / f"{name}-{app}.png" if not spec.dry_run else Path("/tmp/dry.png")
                )
                if not spec.dry_run:
                    if driver is not None:
                        for cmd in driver.commands_for(app):
                            backend.qemu_agent_exec(name, cmd)
                    backend.screenshot(name, actual)
                template = _resolve_template(spec.templates_dir, distro.name, app)
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
            if not spec.dry_run:
                _teardown(backend, name, disk_path)

    return MatrixReport(
        run_id=run_id,
        started_at=started_at,
        finished_at=datetime.now(UTC),
        results=results,
    )


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


def _domain_for(name: DistroName) -> DomainConfig:
    return DomainConfig(
        name=f"screenwright-{name.value.replace('.', '-')}",
        memory_mib=4096,
        vcpus=2,
        disk_gib=20,
        graphics="vnc",
        listen="127.0.0.1",
        enable_3d=False,
    )


def _disk_path(root: Path, distro: DistroName) -> Path:
    return root / f"{distro.value}.qcow2"


__all__ = ["TemplateMatcherPort", "execute", "plan"]

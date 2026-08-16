"""CLI subcommand: matrix (TODO §6)."""

import argparse
import json
from pathlib import Path

from domains.matrix.backend.fake import FakeBackend
from domains.matrix.backend.virsh import VirshBackend
from domains.matrix.drivers import (
    AppCenterDriver,
    DiscoverDriver,
    GnomeSoftwareDriver,
    MintInstallDriver,
    UbuntuDriver,
)
from domains.matrix.models import DistroName, DistroSpec, MatrixRunSpec
from domains.matrix.ports import StoreDriver
from domains.matrix.runner import (
    TemplateMatcherPort,
)
from domains.matrix.runner import (
    execute as matrix_execute,
)
from domains.matrix.runner import (
    plan as matrix_plan,
)
from shared.logging import log_entry
from shared.ports import LibvirtBackend
from shared.results import MatrixReport, Score


def _load_spec(args: argparse.Namespace) -> MatrixRunSpec:
    spec_path = Path(args.spec)
    if not spec_path.exists():
        log_entry(40, "cli.matrix.spec_missing", path=str(spec_path))
        raise FileNotFoundError(spec_path)
    spec_raw = json.loads(spec_path.read_text(encoding="utf-8"))
    distros = [DistroSpec(**d) for d in spec_raw.get("distros", [])]
    return MatrixRunSpec(
        apps=spec_raw.get("apps", []),
        distros=distros,
        batch=spec_raw.get("batch", 2),
        dry_run=not args.execute,
        output_dir=Path(spec_raw.get("output_dir", "vm/reports")),
        templates_dir=(Path(spec_raw["templates_dir"]) if spec_raw.get("templates_dir") else None),
        verify_threshold=float(spec_raw.get("verify_threshold", 0.85)),
    )


def run_matrix_plan(args: argparse.Namespace) -> int:
    try:
        spec = _load_spec(args)
    except (FileNotFoundError, Exception) as exc:
        if isinstance(exc, FileNotFoundError):
            return 2
        log_entry(40, "cli.matrix.spec_invalid", error=str(exc))
        return 2
    steps = matrix_plan(spec)
    log_entry(20, "cli.matrix.plan", steps=len(steps))
    for step in steps:
        print(step.model_dump_json())
    return 0


def _make_backend(args: argparse.Namespace) -> LibvirtBackend:
    name = getattr(args, "backend", "virsh")
    if name == "fake":
        log_entry(
            30,
            "cli.matrix.backend_fake",
            note=(
                "FakeBackend does not start real VMs. Results are illustrative; "
                "the verification matcher compares a screenshot to itself."
            ),
        )
        return FakeBackend()
    if name == "virsh":
        return VirshBackend()
    log_entry(40, "cli.matrix.backend_unknown", backend=name)
    raise ValueError(f"unknown backend: {name}")


def _make_matcher(threshold: float) -> TemplateMatcherPort:
    """Wybiera matcher: OpenCV jeśli dostępny, inaczej Identity."""
    try:
        from domains.verification.template_match import OpenCVTemplateMatcher

        return OpenCVTemplateMatcher(threshold=Score(value=threshold))
    except ImportError:
        from domains.matrix.runner import _default_matcher

        return _default_matcher(threshold)


_DRIVERS_BY_DISTRO: dict[DistroName, StoreDriver] = {
    DistroName.FEDORA_KDE: DiscoverDriver(),
    DistroName.FEDORA_WS: GnomeSoftwareDriver(),
    DistroName.UBUNTU: UbuntuDriver(),
    DistroName.MINT: MintInstallDriver(),
    DistroName.ELEMENTARY: AppCenterDriver(),
}


def _drivers_for_spec(spec: MatrixRunSpec) -> dict[DistroName, StoreDriver]:
    """Zwraca driver tylko dla dystrybucji obecnych w specu.

    Runner pomija qemu-agent-exec dla dystrybucji bez drivera (np. gdy nowa
    dystrybucja nie ma jeszcze implementacji). Dzięki temu dodanie nowej
    dystrybucji do matrix-spec.json nie wysypuje całego przebiegu.
    """
    return {d.name: driver for d in spec.distros if (driver := _DRIVERS_BY_DISTRO.get(d.name))}


def run_matrix_execute(args: argparse.Namespace) -> int:
    try:
        spec = _load_spec(args)
        backend: LibvirtBackend = _make_backend(args)
        matcher: TemplateMatcherPort = _make_matcher(spec.verify_threshold)
        drivers = _drivers_for_spec(spec)
    except (FileNotFoundError, Exception) as exc:
        if isinstance(exc, FileNotFoundError):
            return 2
        log_entry(40, "cli.matrix.spec_invalid", error=str(exc))
        return 2

    if not drivers and not spec.dry_run:
        log_entry(
            30,
            "cli.matrix.no_drivers",
            note="żadna dystrybucja w specu nie ma drivera — krok qemu-agent-exec pominięty",
        )

    report = matrix_execute(spec, backend=backend, matcher=matcher, drivers=drivers)
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        MatrixReport.model_validate(report.model_dump()).model_dump_json(indent=2),
        encoding="utf-8",
    )
    log_entry(20, "cli.matrix.execute.done", path=str(output_path), results=len(report.results))
    return 0


__all__ = ["run_matrix_execute", "run_matrix_plan"]

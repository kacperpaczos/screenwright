"""CLI subcommand: matrix (TODO §6)."""

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

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
from domains.matrix.ports import StoreDriver, StoreProxyLifecycle, StoreProxyProvider
from domains.matrix.runner import (
    TemplateMatcherPort,
)
from domains.matrix.runner import (
    execute as matrix_execute,
)
from domains.matrix.runner import (
    plan as matrix_plan,
)
from domains.matrix.store_proxy import SnapInfo, SnapMedia, StoreProxyConfig, StoreProxyServer
from shared.logging import log_entry
from shared.ports import LibvirtBackend
from shared.results import MatrixReport, Score
from shared.types import AppId


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
        dry_run=_resolve_dry_run(spec_raw, execute=bool(getattr(args, "execute", False))),
        output_dir=Path(spec_raw.get("output_dir", "vm/reports")),
        templates_dir=(Path(spec_raw["templates_dir"]) if spec_raw.get("templates_dir") else None),
        verify_threshold=float(spec_raw.get("verify_threshold", 0.85)),
    )


def _resolve_dry_run(spec_raw: dict[str, Any], *, execute: bool) -> bool:
    """Bez ``--execute`` zawsze sucho; z ``--execute`` decyduje spec.

    ``"dry_run": true`` w JSON-ie jest blokadą, której flaga nie zdejmuje —
    żeby odpalić prawdziwe maszyny trzeba **i** ``--execute``, **i**
    ``dry_run=false`` (albo brak klucza) w specu. Wcześniej CLI po cichu
    nadpisywało wartość z pliku, więc ``matrix-spec.json`` z ``dry_run: true``
    i tak bootował VM-ki.
    """
    if not execute:
        return True
    return bool(spec_raw.get("dry_run", False))


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
        if getattr(args, "execute", False) and spec.dry_run:
            log_entry(
                40,
                "cli.matrix.spec_pins_dry_run",
                spec=str(args.spec),
                hint="spec ma dry_run=true; ustaw dry_run=false (albo usuń klucz), żeby --execute ruszył",
            )
            return 2
        backend: LibvirtBackend = _make_backend(args)
        matcher: TemplateMatcherPort = _make_matcher(spec.verify_threshold)
        drivers = _drivers_for_spec(spec)
        provider = _make_store_proxy_provider(args)
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

    report = matrix_execute(
        spec,
        backend=backend,
        matcher=matcher,
        drivers=drivers,
        store_proxy_provider=provider,
    )
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        MatrixReport.model_validate(report.model_dump()).model_dump_json(indent=2),
        encoding="utf-8",
    )
    log_entry(
        20,
        "cli.matrix.timing_summary",
        phases={k: round(v, 3) for k, v in report.phase_totals().items()},
    )
    log_entry(20, "cli.matrix.execute.done", path=str(output_path), results=len(report.results))
    return 0


def _make_store_proxy_provider(args: argparse.Namespace) -> StoreProxyProvider | None:
    """Konstruuje provider proxy dla dystrybucji z DistroSpec.store_proxy != None."""

    proxy_port = getattr(args, "store_proxy_port", None)
    cli_serve_base = getattr(args, "cli_serve_base", None)

    media_dir = Path(getattr(args, "media_dir", None) or "poc/media")

    def provider(distro: DistroSpec, apps: list[AppId]) -> StoreProxyLifecycle | None:
        if distro.store_proxy != "snap-store":
            return None
        base = cli_serve_base or "http://127.0.0.1:8899"
        manifest = _build_snap_manifest(apps, base, media_dir)
        port = proxy_port or 8900
        config = StoreProxyConfig(manifest=manifest, base_url=base, port=port)
        return StoreProxyServer(config)

    return provider


def media_urls_for(app: AppId, base_url: str, media_dir: Path) -> list[str]:
    """URL-e screenshotów dla appki — tylko dla plików, które realnie istnieją.

    ``cli serve --directory poc/media`` serwuje pliki **z korzenia**
    (``GET /org.kde.kcalc.png``), nie spod ``/screenshots/``. Budowanie URL-i
    z prefiksem dawało 404 na każdym medium. Zwracamy wyłącznie istniejące
    pliki, żeby manifest nigdy nie reklamował martwego URL-a.
    """
    base = base_url.rstrip("/")
    names = [f"{app}.png", *sorted(p.name for p in media_dir.glob(f"{app}-*.png"))]
    return [f"{base}/{name}" for name in names if (media_dir / name).is_file()]


def _build_snap_manifest(apps: list[AppId], base_url: str, media_dir: Path) -> dict[str, SnapInfo]:
    """Mapuje AppId → wpis manifestu kluczowany **nazwą snapu**.

    Nazwa snapu pochodzi z ``UbuntuDriver.SNAP_NAME_MAP`` — jedynego miejsca,
    które wie, jak AppStream AppId przekłada się na nazwę w Snap Store. Appki
    bez mapowania są pomijane: driver i tak nie umie ich otworzyć, więc wpis
    w manifeście byłby martwy.

    ``snap_id`` pozostaje deterministycznym zastępnikiem (nie znamy realnych
    id dla pilot apps). Ścieżka ``/v2/snaps/info`` adresuje po nazwie, więc
    zastępnik jej nie psuje; dotyczy tylko ``/v2/snaps/refresh``, którego bez
    realnych id nie da się dziś obsłużyć — patrz ostrzeżenie w
    ``domains/matrix/store_proxy``.
    """
    out: dict[str, SnapInfo] = {}
    for app in apps:
        snap_name = UbuntuDriver.SNAP_NAME_MAP.get(app)
        if snap_name is None:
            log_entry(30, "cli.matrix.store_proxy.no_snap_mapping", app=app)
            continue
        urls = media_urls_for(app, base_url, media_dir)
        if not urls:
            log_entry(30, "cli.matrix.store_proxy.no_media", app=app, media_dir=str(media_dir))
        out[snap_name] = SnapInfo(
            snap_id="snap_" + hashlib.sha256(app.encode("utf-8")).hexdigest()[:16],
            name=snap_name,
            title=app,
            media=[SnapMedia(url=url) for url in urls],
            description=f"screenwright manifest for {app}",
        )
    return out


__all__ = ["run_matrix_execute", "run_matrix_plan"]

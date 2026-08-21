"""Testy integracyjne — matrix runner end-to-end z FakeBackend."""

from datetime import datetime
from pathlib import Path

import pytest
from domains.matrix.backend.fake import FakeBackend
from domains.matrix.drivers import DiscoverDriver
from domains.matrix.models import DistroName, DistroSpec, MatrixRunSpec
from domains.matrix.runner import _default_matcher, _teardown, _timed, execute, plan
from pydantic import ValidationError
from shared.results import PhaseTiming


def _spec(distros: list[DistroSpec], apps: list[str]) -> MatrixRunSpec:
    return MatrixRunSpec(
        apps=apps,  # type: ignore[arg-type]
        distros=distros,
        dry_run=True,
    )


def _distro(name: DistroName) -> DistroSpec:
    return DistroSpec(name=name, golden_image=Path(f"/tmp/{name.value}.qcow2"))


class TestMatrixRunner:
    def test_dry_run_does_not_call_backend(self) -> None:
        spec = _spec([_distro(DistroName.FEDORA_KDE)], ["org.kde.kcalc"])
        backend = FakeBackend()
        report = execute(spec, backend=backend, matcher=_default_matcher())
        assert len(report.results) == 1
        assert len(backend.calls) == 0

    def test_execute_calls_backend(self, tmp_path: Path) -> None:
        spec = MatrixRunSpec(
            apps=["org.kde.kcalc"],  # type: ignore[arg-type]
            distros=[_distro(DistroName.FEDORA_KDE)],
            dry_run=False,
            output_dir=tmp_path,
        )
        backend = FakeBackend()
        report = execute(spec, backend=backend, matcher=_default_matcher(), work_root=tmp_path)
        assert len(report.results) == 1
        methods = [c.method for c in backend.calls]
        assert "create_overlay" in methods
        assert "create" in methods
        # Per-distro: define i start są pominięte (transient=create only).
        assert "define" not in methods
        assert "start" not in methods
        assert "destroy" in methods
        assert methods.index("destroy") > methods.index("create")

    def test_domain_name_unified_between_xml_and_backend(self, tmp_path: Path) -> None:
        """Nazwa domeny w XML musi być taka sama jak w wywołaniach virsh."""
        spec = MatrixRunSpec(
            apps=["org.kde.kcalc"],  # type: ignore[arg-type]
            distros=[_distro(DistroName.FEDORA_KDE)],
            dry_run=False,
            output_dir=tmp_path,
        )
        backend = FakeBackend()
        execute(spec, backend=backend, matcher=_default_matcher(), work_root=tmp_path)

        # Zbierz nazwy z create i ze screenshot/destroy.
        create_names = {c.args[1] for c in backend.calls if c.method == "create"}
        screenshot_names = {c.args[0] for c in backend.calls if c.method == "screenshot"}
        destroy_names = {c.args[0] for c in backend.calls if c.method == "destroy"}
        assert create_names == screenshot_names == destroy_names
        assert create_names
        xml = next(c.args[0] for c in backend.calls if c.method == "create")
        assert f"<name>{next(iter(create_names))}</name>" in xml

    def test_overlay_created_from_golden(self, tmp_path: Path) -> None:
        golden = tmp_path / "golden.qcow2"
        golden.write_bytes(b"x" * 1024)
        spec = MatrixRunSpec(
            apps=["org.kde.kcalc"],  # type: ignore[arg-type]
            distros=[DistroSpec(name=DistroName.FEDORA_KDE, golden_image=golden)],
            dry_run=False,
            output_dir=tmp_path,
        )
        backend = FakeBackend()
        execute(spec, backend=backend, matcher=_default_matcher(), work_root=tmp_path)
        overlay_calls = [c for c in backend.calls if c.method == "create_overlay"]
        assert len(overlay_calls) == 1
        assert overlay_calls[0].args[0] == golden

    def test_one_boot_per_distro_for_multiple_apps(self, tmp_path: Path) -> None:
        """Wszystkie apps w jednej dystrybucji współdzielą jedną domenę."""
        spec = MatrixRunSpec(
            apps=["org.kde.kcalc", "org.gimp.GIMP"],  # type: ignore[arg-type]
            distros=[_distro(DistroName.FEDORA_KDE)],
            dry_run=False,
            output_dir=tmp_path,
        )
        backend = FakeBackend()
        report = execute(spec, backend=backend, matcher=_default_matcher(), work_root=tmp_path)
        assert len(report.results) == 2
        creates = [c for c in backend.calls if c.method == "create"]
        destroys = [c for c in backend.calls if c.method == "destroy"]
        assert len(creates) == 1
        assert len(destroys) == 1

    def test_drivers_invoked_per_app(self, tmp_path: Path) -> None:
        """Driver jest wywoływany raz na app, wewnątrz bootniętej VM."""
        from domains.matrix.drivers.discover import DiscoverDriver

        class CountingDriver(DiscoverDriver):
            def __init__(self) -> None:
                self.calls: list[str] = []

            def commands_for(self, app):  # type: ignore[override]
                self.calls.append(app)
                return []  # puste — żeby nie wymagać prawdziwego binarnego

        driver = CountingDriver()
        spec = MatrixRunSpec(
            apps=["org.kde.kcalc", "org.gimp.GIMP"],  # type: ignore[arg-type]
            distros=[_distro(DistroName.FEDORA_KDE)],
            dry_run=False,
            output_dir=tmp_path,
        )
        backend = FakeBackend()
        execute(
            spec,
            backend=backend,
            matcher=_default_matcher(),
            drivers={DistroName.FEDORA_KDE: driver},
            work_root=tmp_path,
        )
        assert driver.calls == ["org.kde.kcalc", "org.gimp.GIMP"]

    def test_unknown_distro_in_spec_runs_without_driver(self, tmp_path: Path) -> None:
        """Nieznana dystrybucja bez drivera — runner pomija qemu-agent-exec."""
        spec = MatrixRunSpec(
            apps=["org.kde.kcalc"],  # type: ignore[arg-type]
            distros=[_distro(DistroName.ELEMENTARY)],
            dry_run=False,
            output_dir=tmp_path,
        )
        backend = FakeBackend(raise_on={"qemu_agent_exec"})
        # Nie powinno rzucić — brak drivera = brak wywołań qemu_agent_exec.
        report = execute(spec, backend=backend, matcher=_default_matcher(), work_root=tmp_path)
        assert len(report.results) == 1
        methods = {c.method for c in backend.calls}
        assert "qemu_agent_exec" not in methods

    def test_driver_failure_still_destroys_domain(self, tmp_path: Path) -> None:
        """Wyjątek z qemu_agent_exec nie może zostawić działającej VM.

        qemu_agent_exec podnosi RuntimeError przy niezerowym exitcode w gościu,
        więc bez `finally` awaria drivera zostawiłaby domenę i overlay.
        """

        class _FailingDriver:
            def commands_for(self, app: str) -> list[list[str]]:
                return [["broken-store-command"]]

        spec = MatrixRunSpec(
            apps=["org.kde.kcalc"],  # type: ignore[arg-type]
            distros=[_distro(DistroName.FEDORA_KDE)],
            dry_run=False,
            output_dir=tmp_path,
        )
        backend = FakeBackend(raise_on={"qemu_agent_exec"})
        with pytest.raises(RuntimeError):
            execute(
                spec,
                backend=backend,
                matcher=_default_matcher(),
                drivers={DistroName.FEDORA_KDE: _FailingDriver()},  # type: ignore[dict-item]
                work_root=tmp_path,
            )
        assert "destroy" in {c.method for c in backend.calls}

    def test_driver_failure_removes_overlay(self, tmp_path: Path) -> None:
        class _FailingDriver:
            def commands_for(self, app: str) -> list[list[str]]:
                return [["broken-store-command"]]

        spec = MatrixRunSpec(
            apps=["org.kde.kcalc"],  # type: ignore[arg-type]
            distros=[_distro(DistroName.FEDORA_KDE)],
            dry_run=False,
            output_dir=tmp_path,
        )
        backend = FakeBackend(raise_on={"qemu_agent_exec"})
        with pytest.raises(RuntimeError):
            execute(
                spec,
                backend=backend,
                matcher=_default_matcher(),
                drivers={DistroName.FEDORA_KDE: _FailingDriver()},  # type: ignore[dict-item]
                work_root=tmp_path,
            )
        leftovers = list(tmp_path.glob("*.qcow2"))
        assert leftovers == []

    def test_destroy_failure_does_not_mask_original_error(self, tmp_path: Path) -> None:
        """Gdy i driver, i destroy padną, propagujemy błąd drivera."""
        spec = MatrixRunSpec(
            apps=["org.kde.kcalc"],  # type: ignore[arg-type]
            distros=[_distro(DistroName.FEDORA_KDE)],
            dry_run=False,
            output_dir=tmp_path,
        )

        class _FailingDriver:
            def commands_for(self, app: str) -> list[list[str]]:
                return [["broken-store-command"]]

        backend = FakeBackend(raise_on={"qemu_agent_exec", "destroy"})
        with pytest.raises(RuntimeError):
            execute(
                spec,
                backend=backend,
                matcher=_default_matcher(),
                drivers={DistroName.FEDORA_KDE: _FailingDriver()},  # type: ignore[dict-item]
                work_root=tmp_path,
            )

    def test_plan_with_multiple_distros(self) -> None:
        spec = _spec(
            [_distro(DistroName.FEDORA_KDE), _distro(DistroName.UBUNTU)],
            ["org.kde.kcalc", "org.gimp.GIMP"],
        )
        steps = plan(spec)
        assert len(steps) == 2 * (3 + 2 * 3)

    def test_results_have_timestamps(self) -> None:
        spec = _spec([_distro(DistroName.FEDORA_KDE)], ["org.kde.kcalc"])
        backend = FakeBackend()
        report = execute(spec, backend=backend, matcher=_default_matcher())
        assert isinstance(report.started_at, datetime)
        assert isinstance(report.finished_at, datetime)
        assert report.finished_at >= report.started_at

    def test_run_id_is_set(self) -> None:
        spec = _spec([_distro(DistroName.FEDORA_KDE)], ["org.kde.kcalc"])
        backend = FakeBackend()
        report = execute(spec, backend=backend, matcher=_default_matcher())
        assert report.run_id
        assert len(report.run_id) >= 6

    def test_matcher_receives_real_template_path(self, tmp_path: Path) -> None:
        """Gdy templates_dir jest ustawiony, matcher dostaje realną ścieżkę template."""
        # Arrange
        template = tmp_path / "fedora-kde" / "org.kde.kcalc.png"
        template.parent.mkdir(parents=True, exist_ok=True)
        template.write_bytes(b"\x89PNG fake template")
        spec = MatrixRunSpec(
            apps=["org.kde.kcalc"],  # type: ignore[arg-type]
            distros=[_distro(DistroName.FEDORA_KDE)],
            dry_run=False,
            output_dir=tmp_path,
            templates_dir=tmp_path,
        )
        backend = FakeBackend()

        # Capture what matcher receives
        received: dict[str, tuple[Path, Path]] = {}

        class _Capture:
            threshold = _default_matcher().threshold

            def match(self, template_path: Path, actual_path: Path) -> object:  # type: ignore[type-arg]
                received["paths"] = (template_path, actual_path)
                return _default_matcher().match(template_path, actual_path)

        report = execute(
            spec,
            backend=backend,
            matcher=_Capture(),
            work_root=tmp_path,  # type: ignore[arg-type]
        )
        assert "paths" in received
        template_path, actual_path = received["paths"]
        assert template_path == template
        # actual is the captured screenshot from FakeBackend (may not exist on disk)
        assert actual_path.name.endswith(".png")
        assert len(report.results) == 1


class TestTeardown:
    """`_teardown` leci z `finally` — nie wolno mu rzucić, cokolwiek się stanie."""

    def test_removes_overlay_even_when_destroy_fails(self, tmp_path: Path) -> None:
        overlay = tmp_path / "overlay.qcow2"
        overlay.write_bytes(b"x")
        backend = FakeBackend(raise_on={"destroy"})
        _teardown(backend, "sw-nieistniejaca", overlay)
        assert not overlay.exists()

    def test_removes_overlay_directory(self, tmp_path: Path) -> None:
        overlay_dir = tmp_path / "overlay-dir"
        (overlay_dir / "nested").mkdir(parents=True)
        _teardown(FakeBackend(), "sw-d", overlay_dir)
        assert not overlay_dir.exists()

    def test_missing_overlay_is_not_an_error(self, tmp_path: Path) -> None:
        _teardown(FakeBackend(), "sw-d", tmp_path / "nigdy-nie-istniala.qcow2")

    def test_unlink_failure_is_swallowed(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        overlay = tmp_path / "overlay.qcow2"
        overlay.write_bytes(b"x")

        def _boom(self: Path) -> None:
            raise OSError("read-only filesystem")

        monkeypatch.setattr(Path, "unlink", _boom)
        _teardown(FakeBackend(), "sw-d", overlay)  # nie może rzucić


class TestSeedIsoAttachment:
    """`DistroSpec.seed_iso` musi trafić do XML-a domeny jako cdrom.

    Bez tego cloud-init w gościu nie widzi wolumenu `cidata`, więc user-data
    (desktop, snap-store, autologin) nigdy się nie aplikuje — VM wstaje na
    goły serwer i test sklepu jest niewykonalny.
    """

    def _run(self, tmp_path: Path, seed_iso: Path | None) -> str:
        spec = MatrixRunSpec(
            apps=["org.kde.kcalc"],  # type: ignore[arg-type]
            distros=[
                DistroSpec(
                    name=DistroName.UBUNTU,
                    golden_image=tmp_path / "g.qcow2",
                    seed_iso=seed_iso,
                )
            ],
            dry_run=False,
            output_dir=tmp_path,
        )
        backend = FakeBackend()
        execute(spec, backend=backend, matcher=_default_matcher(), work_root=tmp_path)
        (domain,) = backend.domains.values()
        return domain.xml

    def test_seed_iso_is_attached_as_cdrom(self, tmp_path: Path) -> None:
        seed = tmp_path / "ubuntu-seed.iso"
        seed.write_bytes(b"iso")
        xml = self._run(tmp_path, seed)
        assert 'device="cdrom"' in xml
        assert str(seed) in xml

    def test_no_cdrom_when_seed_iso_absent(self, tmp_path: Path) -> None:
        xml = self._run(tmp_path, None)
        assert 'device="cdrom"' not in xml


class TestDomainOverrides:
    """`DistroSpec.domain_overrides` ma trafiać do XML-a klona.

    Pole istniało od początku, ale runner je ignorował i renderował 4096 MiB /
    2 vCPU na sztywno — nie dało się ani odchudzić maszyny pod warm cache, ani
    wpuścić SPICE na hoście, który go jeszcze ma.
    """

    def _run(self, tmp_path: Path, overrides: dict[str, object]) -> tuple[FakeBackend, str]:
        spec = MatrixRunSpec(
            apps=["org.kde.kcalc"],  # type: ignore[arg-type]
            distros=[
                DistroSpec(
                    name=DistroName.FEDORA_KDE,
                    golden_image=tmp_path / "g.qcow2",
                    domain_overrides=overrides,
                )
            ],
            dry_run=False,
            output_dir=tmp_path,
        )
        backend = FakeBackend()
        execute(spec, backend=backend, matcher=_default_matcher(), work_root=tmp_path)
        (domain,) = backend.domains.values()
        return backend, domain.xml

    def test_overrides_reach_domain_xml(self, tmp_path: Path) -> None:
        _, xml = self._run(tmp_path, {"memory_mib": 2048, "vcpus": 1})
        assert '<memory unit="MiB">2048</memory>' in xml
        assert "<vcpu>1</vcpu>" in xml

    def test_defaults_apply_without_overrides(self, tmp_path: Path) -> None:
        _, xml = self._run(tmp_path, {})
        assert '<memory unit="MiB">4096</memory>' in xml
        assert "<vcpu>2</vcpu>" in xml

    def test_runner_still_owns_name_and_ssh_port(self, tmp_path: Path) -> None:
        backend, xml = self._run(tmp_path, {"memory_mib": 2048})
        (name,) = backend.domains
        assert name.startswith("sw-fedora-kde-")
        assert f"<name>{name}</name>" in xml
        assert '<range start="' in xml

    def test_out_of_range_override_fails_before_backend(self, tmp_path: Path) -> None:
        spec = MatrixRunSpec(
            apps=["org.kde.kcalc"],  # type: ignore[arg-type]
            distros=[
                DistroSpec(
                    name=DistroName.FEDORA_KDE,
                    golden_image=tmp_path / "g.qcow2",
                    domain_overrides={"memory_mib": 100},
                )
            ],
            dry_run=False,
            output_dir=tmp_path,
        )
        backend = FakeBackend()
        with pytest.raises(ValidationError):
            execute(spec, backend=backend, matcher=_default_matcher(), work_root=tmp_path)
        assert backend.calls == []


class TestTimings:
    """Raport ma mówić, gdzie schodzi czas — to jest liczba odniesienia dla Bramki A."""

    def test_timings_record_phases_in_order(self, tmp_path: Path) -> None:
        spec = MatrixRunSpec(
            apps=["org.kde.kcalc", "org.gimp.GIMP"],  # type: ignore[arg-type]
            distros=[_distro(DistroName.FEDORA_KDE)],
            dry_run=False,
            output_dir=tmp_path,
        )
        report = execute(
            spec,
            backend=FakeBackend(),
            matcher=_default_matcher(),
            drivers={DistroName.FEDORA_KDE: DiscoverDriver()},
            work_root=tmp_path,
        )
        phases = [(t.phase, t.app) for t in report.timings]
        assert phases == [
            ("create_overlay", None),
            ("create", None),
            ("launch", "org.kde.kcalc"),
            ("screenshot", "org.kde.kcalc"),
            ("verify", "org.kde.kcalc"),
            ("launch", "org.gimp.GIMP"),
            ("screenshot", "org.gimp.GIMP"),
            ("verify", "org.gimp.GIMP"),
            ("teardown", None),
        ]
        assert all(t.distro == "fedora-kde" for t in report.timings)
        assert all(t.detail["ok"] is True for t in report.timings)
        assert all(t.seconds >= 0.0 for t in report.timings)
        launch = next(t for t in report.timings if t.phase == "launch")
        assert launch.detail["commands"] == 1
        totals = report.phase_totals()
        assert {"create", "launch", "screenshot", "verify", "teardown", "boot", "run_total"} <= set(
            totals
        )

    def test_dry_run_records_only_what_ran(self) -> None:
        spec = _spec([_distro(DistroName.FEDORA_KDE)], ["org.kde.kcalc"])
        report = execute(spec, backend=FakeBackend(), matcher=_default_matcher())
        assert [t.phase for t in report.timings] == ["verify"]

    def test_no_driver_means_no_launch_phase(self, tmp_path: Path) -> None:
        spec = MatrixRunSpec(
            apps=["org.kde.kcalc"],  # type: ignore[arg-type]
            distros=[_distro(DistroName.ELEMENTARY)],
            dry_run=False,
            output_dir=tmp_path,
        )
        report = execute(
            spec, backend=FakeBackend(), matcher=_default_matcher(), work_root=tmp_path
        )
        assert "launch" not in {t.phase for t in report.timings}

    def test_timed_records_failed_phase_with_ok_false(self) -> None:
        timings: list[PhaseTiming] = []
        with (
            pytest.raises(RuntimeError, match="boom"),
            _timed(timings, "fedora-kde", None, "create"),
        ):
            raise RuntimeError("boom")
        assert len(timings) == 1
        assert isinstance(timings[0], PhaseTiming)
        assert timings[0].phase == "create"
        assert timings[0].detail == {"ok": False}
        assert timings[0].seconds >= 0.0

    def test_timed_lets_phase_add_detail(self) -> None:
        timings: list[PhaseTiming] = []
        with _timed(timings, "fedora-kde", "org.kde.kcalc", "launch") as detail:  # type: ignore[arg-type]
            detail["commands"] = 2
        assert timings[0].app == "org.kde.kcalc"
        assert timings[0].detail == {"commands": 2, "ok": True}


class TestStoreProxyIntegration:
    def test_provider_returns_none_no_proxy_calls(self, tmp_path: Path) -> None:
        from domains.matrix.ports import StoreProxyLifecycle

        class _TrackingProvider:
            def __init__(self) -> None:
                self.calls: list[tuple[str, list[str]]] = []

            def __call__(self, distro, apps) -> StoreProxyLifecycle | None:  # type: ignore[type-arg]
                self.calls.append((distro.name.value, list(apps)))
                return None

        provider = _TrackingProvider()
        spec = MatrixRunSpec(
            apps=["org.kde.kcalc"],  # type: ignore[arg-type]
            distros=[DistroSpec(name=DistroName.UBUNTU, golden_image=tmp_path / "g.qcow2")],
            dry_run=False,
            output_dir=tmp_path,
        )
        backend = FakeBackend()
        execute(
            spec,
            backend=backend,
            matcher=_default_matcher(),
            store_proxy_provider=provider,
            work_root=tmp_path,
        )
        assert provider.calls == [("ubuntu-24.04", ["org.kde.kcalc"])]

    def test_provider_returns_proxy_start_and_stop_called(self, tmp_path: Path) -> None:
        class _FakeProxy:
            def __init__(self) -> None:
                self.url = "http://127.0.0.1:8900"
                self.events: list[str] = []

            def start(self) -> None:
                self.events.append("start")

            def wait_ready(self, timeout: float) -> bool:
                self.events.append("wait_ready")
                return True

            def stop(self) -> None:
                self.events.append("stop")

        proxy = _FakeProxy()

        def provider(_distro, _apps):  # type: ignore[type-arg]
            return proxy

        spec = MatrixRunSpec(
            apps=["org.kde.kcalc"],  # type: ignore[arg-type]
            distros=[DistroSpec(name=DistroName.UBUNTU, golden_image=tmp_path / "g.qcow2")],
            dry_run=False,
            output_dir=tmp_path,
        )
        backend = FakeBackend()
        execute(
            spec,
            backend=backend,
            matcher=_default_matcher(),
            store_proxy_provider=provider,
            work_root=tmp_path,
        )
        assert proxy.events == ["start", "wait_ready", "stop"]

    def test_proxy_readiness_is_awaited_before_any_backend_call(self, tmp_path: Path) -> None:
        """Przed `wait_ready()` runner nie ma prawa tknąć backendu.

        Inaczej VM bootuje się równolegle ze startem proxy i pierwsze żądanie
        sklepu ściga się z uvicornem — test przechodzi albo pada losowo.
        """
        backend = FakeBackend()
        seen_at_ready: list[int] = []

        class _FakeProxy:
            url = "http://x"

            def start(self) -> None:
                pass

            def wait_ready(self, timeout: float) -> bool:
                seen_at_ready.append(len(backend.calls))
                return True

            def stop(self) -> None:
                pass

        spec = MatrixRunSpec(
            apps=["org.kde.kcalc"],  # type: ignore[arg-type]
            distros=[DistroSpec(name=DistroName.UBUNTU, golden_image=tmp_path / "g.qcow2")],
            dry_run=False,
            output_dir=tmp_path,
        )
        execute(
            spec,
            backend=backend,
            matcher=_default_matcher(),
            store_proxy_provider=lambda _d, _a: _FakeProxy(),
            work_root=tmp_path,
        )
        assert seen_at_ready == [0]
        assert backend.calls, "po gotowości proxy przebieg ma normalnie bootować VM"

    def test_proxy_not_ready_stops_proxy_and_skips_backend(self, tmp_path: Path) -> None:
        class _NeverReadyProxy:
            url = "http://x"

            def __init__(self) -> None:
                self.events: list[str] = []

            def start(self) -> None:
                self.events.append("start")

            def wait_ready(self, timeout: float) -> bool:
                self.events.append("wait_ready")
                return False

            def stop(self) -> None:
                self.events.append("stop")

        proxy = _NeverReadyProxy()
        spec = MatrixRunSpec(
            apps=["org.kde.kcalc"],  # type: ignore[arg-type]
            distros=[DistroSpec(name=DistroName.UBUNTU, golden_image=tmp_path / "g.qcow2")],
            dry_run=False,
            output_dir=tmp_path,
        )
        backend = FakeBackend()
        with pytest.raises(RuntimeError, match="did not become ready"):
            execute(
                spec,
                backend=backend,
                matcher=_default_matcher(),
                store_proxy_provider=lambda _d, _a: proxy,
                work_root=tmp_path,
            )
        assert proxy.events == ["start", "wait_ready", "stop"]
        assert backend.calls == []

    def test_proxy_stop_called_even_when_driver_fails(self, tmp_path: Path) -> None:
        """driver rzuca wyjątek → proxy.stop() mimo to (finally)."""

        class _FakeProxy:
            def __init__(self) -> None:
                self.events: list[str] = []

            def start(self) -> None:
                self.events.append("start")

            def wait_ready(self, timeout: float) -> bool:
                self.events.append("wait_ready")
                return True

            def stop(self) -> None:
                self.events.append("stop")

            url = "http://x"

        class _FailingDriver:
            distro = DistroName.UBUNTU

            def commands_for(self, app):  # type: ignore[override]
                return [["broken-store-command"]]

        proxy = _FakeProxy()
        spec = MatrixRunSpec(
            apps=["org.kde.kcalc"],  # type: ignore[arg-type]
            distros=[DistroSpec(name=DistroName.UBUNTU, golden_image=tmp_path / "g.qcow2")],
            dry_run=False,
            output_dir=tmp_path,
        )
        backend = FakeBackend(raise_on={"qemu_agent_exec"})
        with pytest.raises(RuntimeError):
            execute(
                spec,
                backend=backend,
                matcher=_default_matcher(),
                drivers={DistroName.UBUNTU: _FailingDriver()},  # type: ignore[dict-item]
                store_proxy_provider=lambda _d, _a: proxy,
                work_root=tmp_path,
            )
        assert proxy.events == ["start", "wait_ready", "stop"]

    def test_dry_run_does_not_invoke_provider(self, tmp_path: Path) -> None:
        from domains.matrix.ports import StoreProxyLifecycle

        class _TrackingProvider:
            def __init__(self) -> None:
                self.calls = 0

            def __call__(self, distro, apps) -> StoreProxyLifecycle | None:  # type: ignore[type-arg]
                self.calls += 1
                return None

        provider = _TrackingProvider()
        spec = _spec([_distro(DistroName.UBUNTU)], ["org.kde.kcalc"])
        backend = FakeBackend()
        execute(
            spec,
            backend=backend,
            matcher=_default_matcher(),
            store_proxy_provider=provider,
        )
        assert provider.calls == 0

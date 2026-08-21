"""Testy jednostkowe — WarmCache: manifest, lookup, commit, invalidate, lock."""

from __future__ import annotations

import os
import socket
from datetime import UTC, datetime
from pathlib import Path  # noqa: TC003  (runtime: tmp_path)

import pytest
from domains.matrix.models import DEFAULT_DOMAIN, DistroName, DistroSpec, DomainConfig
from domains.matrix.warm_cache import (
    BASE_NAME,
    DISK_NAME,
    MANIFEST_NAME,
    STATE_NAME,
    XML_NAME,
    WarmCache,
    WarmManifest,
    hardware_of,
    port_is_free,
    template_name,
)


def _distro(tmp_path: Path) -> DistroSpec:
    golden = tmp_path / "golden.qcow2"
    if not golden.exists():
        golden.write_bytes(b"golden")
    return DistroSpec(name=DistroName.FEDORA_KDE, golden_image=golden)


def _hardware() -> dict[str, object]:
    return hardware_of(DomainConfig(**{**DEFAULT_DOMAIN, "name": "x", "ssh_port": 2222}))


def _built(tmp_path: Path, cache: WarmCache, distro: DistroSpec, *, port: int = 40000) -> None:
    """Symuluje build: prepare → „boot" pisze disk → save pisze state → commit."""
    directory = cache.directory(distro.name)
    disk = cache.prepare(distro.name, "<domain><name>sw-fedora-kde-warm</name></domain>")
    assert disk == directory / DISK_NAME
    disk.write_bytes(b"overlay-after-boot")
    (directory / STATE_NAME).write_bytes(b"ram")
    cache.commit(distro, name=template_name(distro.name), ssh_port=port, hardware=_hardware())


class TestHelpers:
    def test_hardware_excludes_runner_owned_fields(self) -> None:
        hw = _hardware()
        assert "name" not in hw
        assert "ssh_port" not in hw
        assert hw["memory_mib"] == 4096

    def test_template_name_has_no_dots(self) -> None:
        assert template_name(DistroName.UBUNTU) == "sw-ubuntu-24-04-warm"

    def test_port_is_free_detects_a_bound_port(self) -> None:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.bind(("127.0.0.1", 0))
            sock.listen(1)
            port = sock.getsockname()[1]
            assert port_is_free(port) is False
        assert port_is_free(port) is True


class TestLookup:
    def test_no_manifest_means_miss(self, tmp_path: Path) -> None:
        cache = WarmCache(tmp_path / "warm")
        assert cache.lookup(_distro(tmp_path), _hardware()) is None

    def test_built_template_is_found(self, tmp_path: Path) -> None:
        cache = WarmCache(tmp_path / "warm", cache_key="qemu 10")
        distro = _distro(tmp_path)
        _built(tmp_path, cache, distro)
        template = cache.lookup(distro, _hardware())
        assert template is not None
        assert template.manifest.name == "sw-fedora-kde-warm"
        assert template.manifest.ssh_port == 40000
        assert template.base.read_bytes() == b"overlay-after-boot"
        assert not template.disk.exists(), (
            "commit zamraża disk→base; świeży disk tworzy dopiero przebieg"
        )
        assert template.xml.read_text().startswith("<domain>")

    def test_corrupt_manifest_is_a_miss(self, tmp_path: Path) -> None:
        cache = WarmCache(tmp_path / "warm")
        distro = _distro(tmp_path)
        _built(tmp_path, cache, distro)
        (cache.directory(distro.name) / MANIFEST_NAME).write_text("{not json")
        assert cache.lookup(distro, _hardware()) is None

    @pytest.mark.parametrize("missing", [BASE_NAME, STATE_NAME, XML_NAME])
    def test_missing_file_is_a_miss(self, tmp_path: Path, missing: str) -> None:
        cache = WarmCache(tmp_path / "warm")
        distro = _distro(tmp_path)
        _built(tmp_path, cache, distro)
        (cache.directory(distro.name) / missing).unlink()
        assert cache.lookup(distro, _hardware()) is None

    def test_golden_change_is_a_miss(self, tmp_path: Path) -> None:
        cache = WarmCache(tmp_path / "warm")
        distro = _distro(tmp_path)
        _built(tmp_path, cache, distro)
        distro.golden_image.write_bytes(b"golden-rebuilt!")
        os.utime(distro.golden_image, ns=(1, 1))
        assert cache.lookup(distro, _hardware()) is None

    def test_hardware_change_is_a_miss(self, tmp_path: Path) -> None:
        cache = WarmCache(tmp_path / "warm")
        distro = _distro(tmp_path)
        _built(tmp_path, cache, distro)
        smaller = hardware_of(DomainConfig(**{**DEFAULT_DOMAIN, "memory_mib": 2048, "name": "x"}))
        assert cache.lookup(distro, smaller) is None

    def test_hypervisor_change_is_a_miss(self, tmp_path: Path) -> None:
        distro = _distro(tmp_path)
        _built(tmp_path, WarmCache(tmp_path / "warm", cache_key="qemu 10.2"), distro)
        assert (
            WarmCache(tmp_path / "warm", cache_key="qemu 11.0").lookup(distro, _hardware()) is None
        )
        assert WarmCache(tmp_path / "warm", cache_key="qemu 10.2").lookup(distro, _hardware())

    def test_busy_port_is_a_miss(self, tmp_path: Path) -> None:
        cache = WarmCache(tmp_path / "warm")
        distro = _distro(tmp_path)
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.bind(("127.0.0.1", 0))
            sock.listen(1)
            _built(tmp_path, cache, distro, port=sock.getsockname()[1])
            assert cache.lookup(distro, _hardware()) is None
        assert cache.lookup(distro, _hardware()) is not None


class TestCommitAndInvalidate:
    def test_manifest_roundtrip(self, tmp_path: Path) -> None:
        cache = WarmCache(tmp_path / "warm", cache_key="k")
        distro = _distro(tmp_path)
        _built(tmp_path, cache, distro)
        raw = (cache.directory(distro.name) / MANIFEST_NAME).read_text()
        manifest = WarmManifest.model_validate_json(raw)
        assert manifest.golden == str(distro.golden_image)
        assert manifest.golden_size == len(b"golden")
        assert manifest.cache_key == "k"
        assert manifest.created_at.tzinfo is not None
        assert manifest.created_at <= datetime.now(UTC)

    def test_prepare_wipes_previous_template(self, tmp_path: Path) -> None:
        cache = WarmCache(tmp_path / "warm")
        distro = _distro(tmp_path)
        _built(tmp_path, cache, distro)
        cache.prepare(distro.name, "<domain><name>n</name></domain>")
        directory = cache.directory(distro.name)
        assert not (directory / BASE_NAME).exists()
        assert not (directory / STATE_NAME).exists()
        assert not (directory / MANIFEST_NAME).exists()
        assert (directory / XML_NAME).read_text() == "<domain><name>n</name></domain>"

    def test_invalidate_removes_everything_but_keeps_directory(self, tmp_path: Path) -> None:
        cache = WarmCache(tmp_path / "warm")
        distro = _distro(tmp_path)
        _built(tmp_path, cache, distro)
        cache.invalidate(distro.name)
        directory = cache.directory(distro.name)
        assert directory.is_dir()
        assert not any(directory.glob("*.qcow2"))
        assert cache.lookup(distro, _hardware()) is None


class TestLock:
    def test_second_locker_is_refused_while_first_holds(self, tmp_path: Path) -> None:
        cache = WarmCache(tmp_path / "warm")
        with cache.lock(DistroName.FEDORA_KDE) as first:
            assert first is True
            with WarmCache(tmp_path / "warm").lock(DistroName.FEDORA_KDE) as second:
                assert second is False
        with cache.lock(DistroName.FEDORA_KDE) as again:
            assert again is True

    def test_locks_are_per_distro(self, tmp_path: Path) -> None:
        cache = WarmCache(tmp_path / "warm")
        with cache.lock(DistroName.FEDORA_KDE) as a, cache.lock(DistroName.UBUNTU) as b:
            assert (a, b) == (True, True)

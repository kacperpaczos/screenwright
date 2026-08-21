"""Testy jednostkowe — drivery sklepów per dystrybucja."""

from __future__ import annotations

from domains.matrix.drivers import (
    AppCenterDriver,
    DiscoverDriver,
    GnomeSoftwareDriver,
    MintInstallDriver,
    UbuntuDriver,
)
from domains.matrix.models import DistroName


class TestDiscoverDriver:
    def test_distro(self) -> None:
        assert DiscoverDriver.distro == DistroName.FEDORA_KDE

    def test_commands_open_app_page(self) -> None:
        cmds = DiscoverDriver().commands_for("org.kde.kcalc")
        assert cmds == [["plasma-discover", "--application=appstream:org.kde.kcalc"]]

    def test_warmup_opens_discover(self) -> None:
        assert DiscoverDriver().warmup_commands() == [["plasma-discover"]]

    def test_no_quit_option(self) -> None:
        """plasma-discover nie ma --quit (zwraca 1), a guest-exec traktuje
        niezerowy kod jako błąd — jedna taka komenda wysadziłaby przebieg."""
        flat = [arg for cmd in DiscoverDriver().commands_for("org.kde.kcalc") for arg in cmd]
        assert "--quit" not in flat


class TestGnomeSoftwareDriver:
    def test_distro(self) -> None:
        assert GnomeSoftwareDriver.distro == DistroName.FEDORA_WS

    def test_commands_navigate_without_quit(self) -> None:
        """`--quit` przed `--details` robił zimny start per aplikacja i gubił start po restore."""
        cmds = GnomeSoftwareDriver().commands_for("org.gimp.GIMP")  # type: ignore[arg-type]
        assert cmds == [["gnome-software", "--details=org.gimp.GIMP"]]

    def test_warmup_opens_the_store_main_window(self) -> None:
        assert GnomeSoftwareDriver().warmup_commands() == [["gnome-software"]]


class TestUbuntuDriver:
    def test_distro(self) -> None:
        assert UbuntuDriver.distro == DistroName.UBUNTU

    def test_unsupported_returns_empty(self) -> None:
        # TODO §3 — snap-store jest wspierany; unknown app_id bez mapowania
        # → pusta lista (driver pomija krok qemu-agent-exec).
        assert UbuntuDriver().commands_for("org.example.Unknown") == []


class TestMintInstallDriver:
    def test_distro(self) -> None:
        assert MintInstallDriver.distro == DistroName.MINT

    def test_unsupported_returns_empty(self) -> None:
        assert MintInstallDriver().commands_for("org.kde.kcalc") == []


class TestAppCenterDriver:
    def test_distro(self) -> None:
        assert AppCenterDriver.distro == DistroName.ELEMENTARY

    def test_unsupported_returns_empty(self) -> None:
        assert AppCenterDriver().commands_for("org.kde.kcalc") == []


__all__ = []


class TestWarmupDefaults:
    def test_ubuntu_warms_up_snap_store(self) -> None:
        assert UbuntuDriver().warmup_commands() == [["snap-store"]]

    def test_unsupported_drivers_have_no_warmup(self) -> None:
        assert MintInstallDriver().warmup_commands() == []
        assert AppCenterDriver().warmup_commands() == []

"""Testy jednostkowe — driver Ubuntu (snap-store)."""

from __future__ import annotations

import pytest
from domains.matrix.backend.fake import FakeBackend
from domains.matrix.drivers.ubuntu import UbuntuDriver
from domains.matrix.models import DistroName


class TestUbuntuDriverMetadata:
    def test_distro(self) -> None:
        assert UbuntuDriver.distro == DistroName.UBUNTU

    def test_snap_name_map_has_pilot_apps(self) -> None:
        for app_id in (
            "org.kde.kcalc",
            "org.gimp.GIMP",
            "org.inkscape.Inkscape",
            "org.videolan.VLC",
            "org.audacityteam.Audacity",
            "org.blender.Blender",
            "org.gnome.gedit",
            "org.kde.okular",
            "org.libreoffice.LibreOffice",
            "com.transmissionbt.Transmission",
        ):
            assert app_id in UbuntuDriver.SNAP_NAME_MAP, f"brak mapowania dla {app_id}"


class TestUbuntuDriverCommands:
    def setup_method(self) -> None:
        self.driver = UbuntuDriver()

    @pytest.mark.parametrize(
        ("app_id", "expected_snap"),
        [
            ("org.gimp.GIMP", "gimp"),
            ("org.kde.kcalc", "kcalc"),
            ("org.videolan.VLC", "vlc"),
            ("org.libreoffice.LibreOffice", "libreoffice"),
            ("com.transmissionbt.Transmission", "transmission"),
        ],
    )
    def test_known_app_emits_xdg_open(self, app_id: str, expected_snap: str) -> None:
        cmds = self.driver.commands_for(app_id)  # type: ignore[arg-type]
        assert cmds == [["snap-store", f"snap://{expected_snap}"]]

    def test_unknown_app_returns_empty(self) -> None:
        cmds = self.driver.commands_for("org.example.NoSuchApp")  # type: ignore[arg-type]
        assert cmds == []

    def test_commands_are_single_entry(self) -> None:
        """snap-store jest single-instance — driver nie powinien wysyłać quit + open
        (jak gnome-software), bo to zamyka sklep między iteracjami app-ów."""
        cmds = self.driver.commands_for("org.gimp.GIMP")  # type: ignore[arg-type]
        assert len(cmds) == 1


class TestUbuntuDriverPreflight:
    def test_preflight_executes_snap_list(self) -> None:
        backend = FakeBackend(agent_output={"snap list snap-store": "Name Version"})
        driver = UbuntuDriver()
        result = driver.preflight_check(backend, "test-vm")
        assert result == "Name Version"
        assert any(c.method == "qemu_agent_exec" for c in backend.calls)

    def test_preflight_passes_domain_name(self) -> None:
        backend = FakeBackend()
        driver = UbuntuDriver()
        driver.preflight_check(backend, "screenwright-ubuntu")
        call = next(c for c in backend.calls if c.method == "qemu_agent_exec")
        assert call.args[0] == "screenwright-ubuntu"
        assert call.args[1] == ["snap", "list", "snap-store"]


__all__ = []

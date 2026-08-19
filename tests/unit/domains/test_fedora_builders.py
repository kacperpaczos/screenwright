"""Testy jednostkowe — kickstarty Fedory (KDE + Workstation).

Kickstart, który nie parsuje się przez pykickstart, wysypie instalację po
kilkunastu minutach pobierania — i to na konsoli, której nikt nie ogląda.
Walidujemy go tutaj, a nie w VM.
"""

from __future__ import annotations

from pathlib import Path  # noqa: TC003  (tmp_path w sygnaturach testów)

import pytest
from domains.matrix.distro_builders import FedoraKdeBuilder, FedoraWsBuilder
from domains.matrix.models import DistroName
from pykickstart.parser import KickstartParser
from pykickstart.version import makeVersion

_PUBKEY = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5TEST screenwright-ubuntu"

_BUILDERS = [
    pytest.param(FedoraKdeBuilder, DistroName.FEDORA_KDE, "fedora-kde.ks", id="kde"),
    pytest.param(FedoraWsBuilder, DistroName.FEDORA_WS, "fedora-ws.ks", id="ws"),
]


def _render(builder_cls: type, tmp_path: Path, pubkey: str = _PUBKEY) -> str:
    key_path = tmp_path / "id.pub"
    key_path.write_text(pubkey, encoding="utf-8")
    return (
        builder_cls(ssh_pubkey_path=key_path)
        .render_installer(tmp_path / "out")
        .read_text(encoding="utf-8")
    )


class TestKickstartValidity:
    @pytest.mark.parametrize(("builder_cls", "distro", "filename"), _BUILDERS)
    def test_parses_with_pykickstart(
        self, builder_cls: type, distro: DistroName, filename: str, tmp_path: Path
    ) -> None:
        key_path = tmp_path / "id.pub"
        key_path.write_text(_PUBKEY, encoding="utf-8")
        target = builder_cls(ssh_pubkey_path=key_path).render_installer(tmp_path / "out")
        assert target.name == filename
        KickstartParser(makeVersion("F40")).readKickstart(str(target))

    @pytest.mark.parametrize(("builder_cls", "distro", "filename"), _BUILDERS)
    def test_parses_without_ssh_key(
        self, builder_cls: type, distro: DistroName, filename: str, tmp_path: Path
    ) -> None:
        """Brak klucza nie może dać niedomkniętej dyrektywy `sshkey`."""
        target = builder_cls(ssh_pubkey_path=tmp_path / "absent.pub").render_installer(
            tmp_path / "out"
        )
        text = target.read_text(encoding="utf-8")
        assert "sshkey" not in text
        KickstartParser(makeVersion("F40")).readKickstart(str(target))

    @pytest.mark.parametrize(("builder_cls", "distro", "filename"), _BUILDERS)
    def test_sections_are_closed(
        self, builder_cls: type, distro: DistroName, filename: str, tmp_path: Path
    ) -> None:
        text = _render(builder_cls, tmp_path)
        assert text.count("%packages") == 1
        assert text.count("%post") == text.count("%end") - 1


class TestUnattendedContract:
    @pytest.mark.parametrize(("builder_cls", "distro", "filename"), _BUILDERS)
    def test_ssh_is_open(
        self, builder_cls: type, distro: DistroName, filename: str, tmp_path: Path
    ) -> None:
        """Bez sshd i przepuszczonego portu nie wejdziemy na maszynę."""
        text = _render(builder_cls, tmp_path)
        assert _PUBKEY in text
        assert "sshkey --username=test" in text
        assert "services --enabled=sshd" in text
        assert "--service=ssh" in text

    @pytest.mark.parametrize(("builder_cls", "distro", "filename"), _BUILDERS)
    def test_ends_with_poweroff_not_reboot(
        self, builder_cls: type, distro: DistroName, filename: str, tmp_path: Path
    ) -> None:
        """`virt-install --wait -1` wraca na zgaszeniu domeny; reboot zapętla build."""
        text = _render(builder_cls, tmp_path)
        assert text.rstrip().endswith("poweroff")

    @pytest.mark.parametrize(("builder_cls", "distro", "filename"), _BUILDERS)
    def test_guest_agent_and_graphical_target(
        self, builder_cls: type, distro: DistroName, filename: str, tmp_path: Path
    ) -> None:
        text = _render(builder_cls, tmp_path)
        assert "qemu-guest-agent" in text
        assert "graphical.target" in text

    @pytest.mark.parametrize(("builder_cls", "distro", "filename"), _BUILDERS)
    def test_initial_setup_disabled(
        self, builder_cls: type, distro: DistroName, filename: str, tmp_path: Path
    ) -> None:
        """Ekran powitalny przykryłby sklep na każdym zrzucie."""
        assert "initial-setup" in _render(builder_cls, tmp_path)


class TestWelcomeWindowsSuppressed:
    """Okna powitalne zasłaniają sklep na zrzucie.

    Zweryfikowane na żywo: na Fedorze WS modal „Welcome to Fedora Linux 44"
    (gnome-tour) wylądował na wierzchu strony GIMP-a w GNOME Software.
    `initial-setup` to OSOBNY komponent i jego wyłączenie tego nie załatwia.
    """

    def test_gnome_tour_removed(self, tmp_path: Path) -> None:
        text = _render(FedoraWsBuilder, tmp_path)
        assert "rm -f /etc/xdg/autostart/org.gnome.Tour.desktop" in text
        assert "dnf remove -y gnome-tour" in text

    def test_plasma_welcome_removed(self, tmp_path: Path) -> None:
        text = _render(FedoraKdeBuilder, tmp_path)
        assert "rm -f /etc/xdg/autostart/plasma-welcome.desktop" in text
        assert "dnf remove -y plasma-welcome" in text

    def test_plasma_setup_service_disabled(self, tmp_path: Path) -> None:
        """plasma-setup.service przejmuje seat0 przed autologinem SDDM-a.

        Bez tego sesja graficzna należy do użytkownika `plasma-setup`, a nie do
        `test` — Discover nie ma się gdzie narysować. Sama konfiguracja
        autologinu tego NIE naprawia (zweryfikowane na żywo).
        """
        text = _render(FedoraKdeBuilder, tmp_path)
        assert "systemctl disable plasma-setup.service" in text
        assert "dnf remove -y plasma-setup" in text

    @pytest.mark.parametrize(("builder_cls", "distro", "filename"), _BUILDERS)
    def test_initial_setup_also_disabled(
        self, builder_cls: type, distro: DistroName, filename: str, tmp_path: Path
    ) -> None:
        """Oba mechanizmy naraz — jeden nie zastępuje drugiego."""
        assert "initial-setup" in _render(builder_cls, tmp_path)


class TestGuestAccess:
    @pytest.mark.parametrize(("builder_cls", "distro", "filename"), _BUILDERS)
    def test_passwordless_sudo(
        self, builder_cls: type, distro: DistroName, filename: str, tmp_path: Path
    ) -> None:
        """SSH bez terminala nie poda hasła — samo `wheel` blokuje diagnostykę.

        Zweryfikowane na żywo: `sudo` przez ssh bez -t kończyło się
        „a terminal is required to read the password".
        """
        text = _render(builder_cls, tmp_path)
        assert "test ALL=(ALL) NOPASSWD:ALL" in text
        assert "/etc/sudoers.d/90-test-nopasswd" in text


class TestAutologin:
    def test_kde_writes_plasmalogin_config(self, tmp_path: Path) -> None:
        """Fedora 44 KDE porzuciła SDDM na rzecz plasma-login-manager.

        Konfiguracja w /etc/sddm.conf.d/ jest wtedy ignorowana i maszyna staje
        na ekranie logowania — zweryfikowane na żywo.
        """
        text = _render(FedoraKdeBuilder, tmp_path)
        assert "/etc/plasmalogin.conf.d" in text
        assert "/etc/sddm.conf.d" in text, "starsze wydania nadal używają SDDM-a"

    def test_ws_writes_gdm_config(self, tmp_path: Path) -> None:
        text = _render(FedoraWsBuilder, tmp_path)
        assert "/etc/gdm/custom.conf" in text
        assert "AutomaticLogin=test" in text


class TestStoreCoverage:
    def test_kde_installs_plasma_for_discover(self, tmp_path: Path) -> None:
        text = _render(FedoraKdeBuilder, tmp_path)
        assert "@^kde-desktop-environment" in text
        assert "[Autologin]" in text
        assert "Session=plasma" in text

    def test_workstation_installs_gnome_software(self, tmp_path: Path) -> None:
        text = _render(FedoraWsBuilder, tmp_path)
        assert "@^workstation-product-environment" in text
        assert "gnome-software" in text
        assert "AutomaticLogin=test" in text


class TestGoldenPaths:
    def test_kde(self, tmp_path: Path) -> None:
        assert FedoraKdeBuilder().golden_path(tmp_path) == tmp_path / "golden" / "fedora-kde.qcow2"

    def test_ws(self, tmp_path: Path) -> None:
        assert FedoraWsBuilder().golden_path(tmp_path) == tmp_path / "golden" / "fedora-ws.qcow2"

    def test_distro_names(self) -> None:
        assert FedoraKdeBuilder.name == DistroName.FEDORA_KDE
        assert FedoraWsBuilder.name == DistroName.FEDORA_WS


__all__: list[str] = []

"""Testy jednostkowe — NoCloud seed dla Ubuntu 24.04.

Golden image powstaje z **serwerowego** cloud image'a, więc wszystko, co
potrzebne do testu sklepu (desktop, snap-store, autologin), musi dołożyć
cloud-init. Brak któregokolwiek elementu = VM wstaje na konsolę tekstową
i `virsh screenshot` łapie prompt logowania zamiast sklepu.
"""

from __future__ import annotations

from pathlib import Path  # noqa: TC003  (tmp_path w sygnaturach testów)
from typing import TYPE_CHECKING

import yaml
from domains.matrix.distro_builders.ubuntu import UbuntuBuilder
from domains.matrix.models import DistroName

if TYPE_CHECKING:
    import pytest


def _user_data(tmp_path: Path, pubkey: str = "ssh-ed25519 AAAAC3Nz test@host") -> str:
    key_path = tmp_path / "id.pub"
    key_path.write_text(pubkey, encoding="utf-8")
    out_dir = tmp_path / "seed"
    UbuntuBuilder(ssh_pubkey_path=key_path).render_installer(out_dir)
    return (out_dir / "user-data").read_text(encoding="utf-8")


class TestRenderInstaller:
    def test_writes_nocloud_pair(self, tmp_path: Path) -> None:
        key_path = tmp_path / "id.pub"
        key_path.write_text("ssh-ed25519 AAAAC3Nz test@host", encoding="utf-8")
        out_dir = tmp_path / "seed"
        result = UbuntuBuilder(ssh_pubkey_path=key_path).render_installer(out_dir)
        assert result == out_dir
        assert (out_dir / "user-data").is_file()
        assert (out_dir / "meta-data").is_file()

    def test_distro_name(self) -> None:
        assert UbuntuBuilder.name == DistroName.UBUNTU

    def test_golden_path(self, tmp_path: Path) -> None:
        assert UbuntuBuilder().golden_path(tmp_path) == tmp_path / "golden" / "ubuntu-24.04.qcow2"


class TestUserDataContents:
    def test_is_valid_cloud_config(self, tmp_path: Path) -> None:
        raw = _user_data(tmp_path)
        assert raw.startswith("#cloud-config")
        parsed = yaml.safe_load(raw)
        assert isinstance(parsed, dict)

    def test_installs_full_desktop_not_minimal(self, tmp_path: Path) -> None:
        """Pełny ubuntu-desktop — chcemy dokładnie to środowisko, co użytkownik."""
        packages = yaml.safe_load(_user_data(tmp_path))["packages"]
        assert "ubuntu-desktop" in packages
        assert "ubuntu-desktop-minimal" not in packages

    def test_installs_gnome_software(self, tmp_path: Path) -> None:
        """Ubuntu 24.04 nie daje GNOME Software domyślnie — bez tego nie ma
        czego porównywać z Fedorą Workstation."""
        packages = yaml.safe_load(_user_data(tmp_path))["packages"]
        assert "gnome-software" in packages

    def test_apt_is_fully_unattended(self, tmp_path: Path) -> None:
        """Provisioning leci bez konsoli — jeden debconf-prompt zawiesza build."""
        conf = yaml.safe_load(_user_data(tmp_path))["apt"]["conf"]
        assert 'APT::Get::Assume-Yes "true";' in conf
        assert "--force-confold" in conf

    def test_powers_off_when_done(self, tmp_path: Path) -> None:
        """`virt-install --wait -1` wraca na zgaszeniu domeny."""
        assert yaml.safe_load(_user_data(tmp_path))["power_state"]["mode"] == "poweroff"


class TestFirstRunChromeSuppressed:
    """Chrom pierwszego uruchomienia zasłania sklep na zrzucie ekranu.

    Zweryfikowane na żywo: bez tego pierwszy boot pokazuje kreator „Welcome to
    Ubuntu" i modal „Software Updater" na wierzchu okna snap-store.
    """

    def _runcmd(self, tmp_path: Path) -> str:
        parsed = yaml.safe_load(_user_data(tmp_path))
        return "\n".join(str(entry[-1]) for entry in parsed["runcmd"])

    def test_gnome_initial_setup_marked_done(self, tmp_path: Path) -> None:
        assert "gnome-initial-setup-done" in self._runcmd(tmp_path)

    def test_gnome_initial_setup_autostart_removed(self, tmp_path: Path) -> None:
        assert "gnome-initial-setup-first-login.desktop" in self._runcmd(tmp_path)

    def test_update_notifier_autostart_removed(self, tmp_path: Path) -> None:
        """Modal „Software Updater" wyskakuje na wierzch okna sklepu."""
        assert "update-notifier.desktop" in self._runcmd(tmp_path)

    def test_periodic_apt_disabled(self, tmp_path: Path) -> None:
        runcmd = self._runcmd(tmp_path)
        assert "APT::Periodic::Update-Package-Lists" in runcmd
        assert "apt-daily.timer" in runcmd

    def test_apport_disabled(self, tmp_path: Path) -> None:
        assert "apport" in self._runcmd(tmp_path)

    def test_installs_snap_store(self, tmp_path: Path) -> None:
        """snap-store to snap, nie pakiet apt — musi iść przez `snap: commands:`."""
        parsed = yaml.safe_load(_user_data(tmp_path))
        commands = parsed["snap"]["commands"]
        assert ["install", "snap-store"] in commands

    def test_installs_qemu_guest_agent(self, tmp_path: Path) -> None:
        """Bez agenta runner nie wykona qemu-agent-exec ani nie znajdzie IP."""
        parsed = yaml.safe_load(_user_data(tmp_path))
        assert "qemu-guest-agent" in parsed["packages"]

    def test_enables_autologin_and_graphical_target(self, tmp_path: Path) -> None:
        raw = _user_data(tmp_path)
        assert "AutomaticLoginEnable=true" in raw
        assert "graphical.target" in raw

    def test_injects_ssh_pubkey(self, tmp_path: Path) -> None:
        parsed = yaml.safe_load(_user_data(tmp_path, "ssh-ed25519 AAAAKEY marker@host"))
        (user,) = parsed["users"]
        assert user["ssh_authorized_keys"] == ["ssh-ed25519 AAAAKEY marker@host"]

    def test_missing_pubkey_still_renders(self, tmp_path: Path) -> None:
        out_dir = tmp_path / "seed"
        UbuntuBuilder(ssh_pubkey_path=tmp_path / "absent.pub").render_installer(out_dir)
        parsed = yaml.safe_load((out_dir / "user-data").read_text(encoding="utf-8"))
        assert isinstance(parsed, dict)


class TestPubkeyResolution:
    def test_env_var_wins(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        key_path = tmp_path / "z-env.pub"
        key_path.write_text("ssh-ed25519 AAAAENV env@host", encoding="utf-8")
        monkeypatch.setenv("SCREENWRIGHT_SSH_PUBKEY_PATH", str(key_path))
        out_dir = tmp_path / "seed"
        UbuntuBuilder().render_installer(out_dir)
        parsed = yaml.safe_load((out_dir / "user-data").read_text(encoding="utf-8"))
        (user,) = parsed["users"]
        assert user["ssh_authorized_keys"] == ["ssh-ed25519 AAAAENV env@host"]

    def test_falls_back_to_default_path(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.delenv("SCREENWRIGHT_SSH_PUBKEY_PATH", raising=False)
        default = tmp_path / "screenwright_ubuntu.pub"
        default.write_text("ssh-ed25519 AAAADEFAULT default@host", encoding="utf-8")
        monkeypatch.setattr("domains.matrix.distro_builders._ssh.DEFAULT_PUBKEY", default)
        assert UbuntuBuilder()._ssh_pubkey_path == default

    def test_no_key_anywhere_resolves_to_none(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.delenv("SCREENWRIGHT_SSH_PUBKEY_PATH", raising=False)
        monkeypatch.setattr(
            "domains.matrix.distro_builders._ssh.DEFAULT_PUBKEY", tmp_path / "absent.pub"
        )
        assert UbuntuBuilder()._ssh_pubkey_path is None


__all__: list[str] = []

"""Driver Ubuntu (snap-store).

Domyślnym sklepem Ubuntu 24.04+ jest snap-store (snap ``snap-store``). Aby
wyświetlić stronę konkretnego snapu driver używa deep-linku
``xdg-open snap://<snap-name>``. snap-store jest single-instance (jak Discover),
więc kolejne wywołanie aktywuje istniejące okno i przechodzi na nową stronę.

Mapowanie ``AppId → snap_name`` jest jawne (``SNAP_NAME_MAP``) — snapd
nie akceptuje identyfikatorów AppStream/AppId w URI ``snap://``, tylko
oficjalne nazwy snapów. Dla AppId bez wpisu driver zwraca puste ``commands_for``
i loguje warning, a runner pominie krok qemu-agent-exec dla tego (distro, app).

Podmiana screenshotów odbywa się poza driverem przez ``snap-store-proxy``
(``domains/matrix/store_proxy.py``) ustawiony w VM przez
``snap set core proxy.store=http://10.0.2.2:<port>``. Driver nie wie o
proxy — po prostu otwiera snap-store; snapd zwraca metadane z naszego proxy.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar

from shared.logging import log_entry

from domains.matrix.models import DistroName

if TYPE_CHECKING:
    from shared.ports import LibvirtBackend
    from shared.types import AppId


class UbuntuDriver:
    """Adapter snap-store."""

    distro = DistroName.UBUNTU

    SNAP_NAME_MAP: ClassVar[dict[str, str]] = {
        "org.kde.kcalc": "kcalc",
        "org.gimp.GIMP": "gimp",
        "org.inkscape.Inkscape": "inkscape",
        "org.videolan.VLC": "vlc",
        "org.audacityteam.Audacity": "audacity",
        "org.blender.Blender": "blender",
        "org.gnome.gedit": "gedit",
        "org.kde.okular": "okular",
        "org.libreoffice.LibreOffice": "libreoffice",
        "com.transmissionbt.Transmission": "transmission",
    }

    def commands_for(self, app: AppId) -> list[list[str]]:
        snap_name = self.SNAP_NAME_MAP.get(app)
        if snap_name is None:
            log_entry(
                40,
                "matrix.driver.ubuntu.no_snap_mapping",
                app=app,
                note="brak wpisu w SNAP_NAME_MAP; pomijam krok",
            )
            return []
        log_entry(20, "matrix.driver.ubuntu.snap_open", app=app, snap_name=snap_name)
        return [
            ["xdg-open", f"snap://{snap_name}"],
        ]

    def warmup_commands(self) -> list[list[str]]:
        return [["snap-store"]]

    def window_probe(self) -> list[str] | None:
        """Okno snap-store wg ``org.gnome.Shell.Introspect`` (app-id snapa zaczyna się od ``snap-store``)."""
        return [
            "sh",
            "-c",
            "gsettings set org.gnome.shell introspect true 2>/dev/null; "
            "gdbus call --session --dest org.gnome.Shell --object-path /org/gnome/Shell/Introspect "
            "--method org.gnome.Shell.Introspect.GetWindows 2>/dev/null "
            "| grep -q -E 'snap-store|io.snapcraft.Store' && echo yes || echo no",
        ]

    def preflight_check(self, backend: LibvirtBackend, domain: str) -> str:
        """Sprawdź czy snap-store jest zainstalowany w VM. Zwraca stdout."""
        return backend.qemu_agent_exec(domain, ["snap", "list", "snap-store"], timeout=15.0)


__all__ = ["UbuntuDriver"]

"""Driver GNOME Software.

``gnome-software --details=<id>`` na działającej instancji tylko przełącza
stronę; bez działającej instancji staje się nią sam. Wcześniejsze ``--quit``
przed ``--details`` ubijało instancję autostartu (``--gapplication-service``)
i robiło zimny start (~45 s) dla **każdej** aplikacji, a po ``virsh restore``
gubiło w ogóle uruchomienie: ``systemd-run --wait`` czeka na klienta
``--quit``, nie na zgon instancji, więc ``--details`` trafiało do umierającego
procesu (zmierzone 2026-08-22, ``docs/matrix-timing.md``).
"""

from shared.logging import log_entry
from shared.types import AppId

from domains.matrix.models import DistroName


class GnomeSoftwareDriver:
    distro = DistroName.FEDORA_WS

    def commands_for(self, app: AppId) -> list[list[str]]:
        log_entry(20, "matrix.driver.gnome_software.launch", app=app)
        return [["gnome-software", f"--details={app}"]]

    def warmup_commands(self) -> list[list[str]]:
        return [["gnome-software"]]

    def window_probe(self) -> list[str] | None:
        """Okno GNOME Software wg ``org.gnome.Shell.Introspect`` (app-id ``org.gnome.Software``)."""
        return [
            "sh",
            "-c",
            "gsettings set org.gnome.shell introspect true 2>/dev/null; "
            "gdbus call --session --dest org.gnome.Shell --object-path /org/gnome/Shell/Introspect "
            "--method org.gnome.Shell.Introspect.GetWindows 2>/dev/null "
            "| grep -q org.gnome.Software && echo yes || echo no",
        ]

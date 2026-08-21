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
        # GNOME Shell 50 odmawia ``org.gnome.Shell.Introspect.GetWindows`` („not
        # allowed") nawet z ``org.gnome.shell introspect=true``, a eksport GTK
        # ``/org/gnome/Software/window/1`` istnieje także dla ukrytego okna usługi
        # ``--gapplication-service`` (sprawdzone 2026-08-22). Decydują klatki.
        return None

"""Driver GNOME Software."""

from shared.logging import log_entry
from shared.types import AppId

from domains.matrix.models import DistroName


class GnomeSoftwareDriver:
    distro = DistroName.FEDORA_WS

    def commands_for(self, app: AppId) -> list[list[str]]:
        log_entry(20, "matrix.driver.gnome_software.launch", app=app)
        return [
            ["gnome-software", "--quit"],
            ["gnome-software", f"--details={app}"],
        ]

"""Driver Ubuntu.

Ubuntu ma wiele software centres (Snap Store, GNOME Software, AppStream
DEB). TODO §3 research ma rozstrzygnąć, który testujemy — do tego czasu
driver jest pusty: runner pominie krok qemu-agent-exec, a screenshot
zostanie wykonany na domyślnym widoku sklepu po restarcie sesji X.
"""

from shared.logging import log_entry
from shared.types import AppId

from domains.matrix.models import DistroName


class UbuntuDriver:
    distro = DistroName.UBUNTU

    def commands_for(self, app: AppId) -> list[list[str]]:
        log_entry(
            30,
            "matrix.driver.ubuntu.unsupported",
            app=app,
            note="TODO §3: pick snap-store vs gnome-software vs both",
        )
        return []


__all__ = ["UbuntuDriver"]

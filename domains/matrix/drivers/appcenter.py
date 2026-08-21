"""Driver elementary OS AppCenter.

TODO §3: badanie prezentacji w sklepach. AppCenter (flatpak-based) nie ma
oficjalnego CLI. Kandydaci:

    io.elementary.appcenter --search kcalc      # prawdopodobnie nie istnieje
    dbus-send --dest=io.elementary.appcenter \\
        /io/elementary/appcenter \\
        io.elementary.appcenter.Open string:org.kde.kcalc.desktop

Do czasu weryfikacji driver zwraca puste commands_for — runner pominie
krok qemu-agent-exec. Jawna decyzja "nieobsługiwane" jest lepsza niż
placeholder [["true"]], który raportował sukces za nic.
"""

from shared.logging import log_entry
from shared.types import AppId

from domains.matrix.models import DistroName


class AppCenterDriver:
    distro = DistroName.ELEMENTARY

    def commands_for(self, app: AppId) -> list[list[str]]:
        log_entry(
            30,
            "matrix.driver.appcenter.unsupported",
            app=app,
            note="no CLI/D-Bus verified for TODO §3; skipping per-app navigation",
        )
        return []

    def warmup_commands(self) -> list[list[str]]:
        return []

    def window_probe(self) -> list[str] | None:
        return None


__all__ = ["AppCenterDriver"]

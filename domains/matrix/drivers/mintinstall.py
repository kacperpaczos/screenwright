"""Driver Linux Mint (mintinstall).

TODO §3: badanie prezentacji w sklepach. mintinstall (Python+GTK3) nie ma
oficjalnego CLI do otwarcia strony aplikacji. Kandydaci do zbadania:

    mintinstall --search kcalc                  # otwiera search view
    mintinstall --package-info kcalc            # jeśli istnieje
    dbus-send --session --dest=org.linuxmint.mintinstall \\
        /org/linuxmint/mintinstall \\
        org.linuxmint.mintinstall.ShowPackage string:kcalc

Do czasu weryfikacji driver zwraca puste commands_for — runner wówczas
pominie krok qemu-agent-exec dla tej dystrybucji, a wynik weryfikacji
przejdzie tylko jeśli template jest zgodny z domyślnym widokiem sklepu.
Jawna decyzja "nieobsługiwane" jest lepsza niż wcześniejszy placeholder
[["true"]], który raportował sukces za nic.
"""

from shared.logging import log_entry
from shared.types import AppId

from domains.matrix.models import DistroName


class MintInstallDriver:
    distro = DistroName.MINT

    def commands_for(self, app: AppId) -> list[list[str]]:
        log_entry(
            30,
            "matrix.driver.mintinstall.unsupported",
            app=app,
            note="no CLI/D-Bus verified for TODO §3; skipping per-app navigation",
        )
        return []

    def warmup_commands(self) -> list[list[str]]:
        return []


__all__ = ["MintInstallDriver"]

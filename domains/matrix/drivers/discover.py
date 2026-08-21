"""Driver KDE Discover.

plasma-discover ma opcję `--application <appstream-url>` otwierającą stronę
aplikacji bezpośrednio. Działa z Discover 6.7.4 (potwierdzone na Fedorze 44,
2026-08-16). Stary pomysł (D-Bus `org.kde.discover.openApp`) nie działa —
Discover nie eksportuje takiej metody (jest tylko `org.kde.discover.notifier`,
to inny proces).
"""

from shared.types import AppId

from domains.matrix.models import DistroName


class DiscoverDriver:
    distro = DistroName.FEDORA_KDE

    def commands_for(self, app: AppId) -> list[list[str]]:
        # Discover jest single-instance (KDBusService::Unique), więc kolejne
        # --application aktywuje istniejące okno i przechodzi na nową stronę.
        # Restart jest zbędny; plasma-discover nie ma opcji --quit.
        return [
            ["plasma-discover", f"--application=appstream:{app}"],
        ]

    def warmup_commands(self) -> list[list[str]]:
        return [["plasma-discover"]]


__all__ = ["DiscoverDriver"]

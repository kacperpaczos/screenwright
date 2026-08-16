"""Builder elementary OS 8 — brak unattended (instalacja ręczna)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from shared.logging import log_entry

from domains.matrix.models import DistroName

if TYPE_CHECKING:
    from pathlib import Path


class ElementaryBuilder:
    name = DistroName.ELEMENTARY

    def render_installer(self, out_dir: Path) -> Path:
        target = out_dir / "elementary-notes.md"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(_NOTES, encoding="utf-8")
        log_entry(20, "matrix.elementary.manual_install", path=str(target))
        return target

    def golden_path(self, images_dir: Path) -> Path:
        return images_dir / "golden" / "elementary-8.qcow2"


_NOTES = """# elementary OS 8 — instalacja ręczna

Brak unattended install (upstream issue elementary/installer#503).

## Kroki (jednorazowo na release)

1. Pobierz ISO z https://elementary.io/.
2. `virt-install --name elementary-build --cdrom elementaryos-8...iso ...`
3. Zainstaluj ręcznie (autologin dla `test`, hasło `test`).
4. Po instalacji:
   - `apt install qemu-guest-agent spice-vdagent`
   - `systemctl enable qemu-guest-agent`
   - Wyłącz Initial Setup / blanking / lock screen.
5. `fstrim -a`
6. `virt-sparsify --compress elementary-build.qcow2 elementary-8.qcow2`
7. `chmod 444 elementary-8.qcow2`
"""


__all__ = ["ElementaryBuilder"]

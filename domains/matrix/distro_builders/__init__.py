"""Adaptery DistroBuilder per dystrybucja.

Fedora WS/KDE zbudowane teraz deklaratywnie Packerem (`packer/fedora.pkr.hcl`,
cloud-init) — buildery Anacondy wycofane 2026-08-23. `UbuntuBuilder` zostaje:
reużywa go `packer/build-ubuntu.sh` do renderu NoCloud seed. `MintBuilder`/
`ElementaryBuilder` zostają pod Fazę 3 (odłożoną, `TODO.md §9`).
"""

from domains.matrix.distro_builders.elementary import ElementaryBuilder
from domains.matrix.distro_builders.mint import MintBuilder
from domains.matrix.distro_builders.ubuntu import UbuntuBuilder

__all__ = [
    "ElementaryBuilder",
    "MintBuilder",
    "UbuntuBuilder",
]

"""Domena matrix — prymitywy automatyki VM i budowa golden images.

Silnik uruchamiania matrycy (runner/warm_cache/drivers/store_proxy) został
wycofany 2026-08-22 na rzecz stosu Ansible (kolektory + `deploy-override`).
Zostają prymitywy VM (`backend`, `guest`) i budowniczowie golden
(`distro_builders`) do czasu, aż zastąpi je Packer + repo-tool `visual-check`
(patrz `BACKLOG.md`).
"""

from domains.matrix.models import (
    DistroName,
    DistroSpec,
    DomainConfig,
    MatrixRunSpec,
    MatrixStep,
)

__all__ = [
    "DistroName",
    "DistroSpec",
    "DomainConfig",
    "MatrixRunSpec",
    "MatrixStep",
]

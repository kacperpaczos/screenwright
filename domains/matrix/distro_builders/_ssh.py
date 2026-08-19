"""Wspólne rozwiązywanie klucza publicznego hosta dla builderów dystrybucji.

Każdy builder wstrzykuje ten sam klucz do instalatora, żeby po instalacji
dało się wejść na VM przez SSH bez hasła (``vm/scripts/ubuntu-ssh.sh`` i
diagnostyka na tym stoją). Kolejność: zmienna środowiskowa → domyślna
ścieżka → brak klucza.
"""

from __future__ import annotations

import os
from pathlib import Path

DEFAULT_PUBKEY = Path.home() / ".ssh" / "screenwright_ubuntu.pub"
ENV_VAR = "SCREENWRIGHT_SSH_PUBKEY_PATH"


def resolve_pubkey_path(explicit: Path | None = None) -> Path | None:
    """Ścieżka do klucza publicznego albo None, gdy nigdzie go nie ma."""
    if explicit is not None:
        return explicit
    env = os.environ.get(ENV_VAR)
    if env:
        return Path(env)
    if DEFAULT_PUBKEY.exists():
        return DEFAULT_PUBKEY
    return None


def load_pubkey(path: Path | None) -> str:
    """Treść klucza publicznego; pusty string, gdy pliku nie ma.

    Pusty wynik jest świadomie dozwolony — renderowanie instalatora nie może
    się wysypać tylko dlatego, że ktoś nie odpalił jeszcze build-keypair.sh.
    Skrypty budujące sprawdzają obecność klucza osobno i głośno.
    """
    if path is None or not path.exists():
        return ""
    return path.read_text(encoding="utf-8").strip()


__all__ = ["DEFAULT_PUBKEY", "ENV_VAR", "load_pubkey", "resolve_pubkey_path"]

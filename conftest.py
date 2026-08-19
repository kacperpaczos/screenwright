"""Root conftest — dodaje katalog projektu do sys.path dla testów.
importos musi widzieć moduły ``domains``, ``shared``, ``cli``, ``vm``.
"""

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

"""Helpery do pracy z pydantic w hot path."""

import os
import random
from typing import Any, TypeVar

from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)


def construct_validated(
    cls: type[T],
    data: dict[str, Any],
    sample_rate: int = 100,
    seed: int | None = None,
) -> T:
    """Hybrid: konstrukcja bez walidacji per wpis, ale pełna walidacja co N-ty wpis.

    `sample_rate=100` oznacza: pełna walidacja dla ~1% wpisów (losowo).
    W testach z `seed` zachowuje się deterministycznie.
    """
    rng = random.Random(seed)
    if rng.randint(1, sample_rate) == 1:
        return cls.model_validate(data)
    return cls.model_construct(**data)


def strict_validate(cls: type[T], data: dict[str, Any]) -> T:
    """Pełna walidacja — używana na granicach I/O."""
    return cls.model_validate(data)


def is_test_mode() -> bool:
    return os.environ.get("SCREENWRIGHT_TESTS_FAST") == "1"


__all__ = ["construct_validated", "is_test_mode", "strict_validate"]

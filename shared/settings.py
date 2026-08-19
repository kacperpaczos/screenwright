"""Konfiguracja runtime przez pydantic-settings."""

from __future__ import annotations

from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

DEFAULT_LIBVIRT_URI = "qemu:///session"


def _default_image_root() -> Path:
    """Katalog obrazów w HOME — tryb session nie ma praw do /var/lib/libvirt."""
    return Path.home() / ".local" / "share" / "screenwright" / "images"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="SCREENWRIGHT_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    http_timeout_connect: float = 10.0
    http_timeout_read: float = 30.0
    http_max_retries: int = 3
    http_user_agent: str = "screenwright/0.2 (+https://github.com/screenwright/screenwright)"

    corpus_dir: Path = Path("corpus")
    verify_threshold: float = 0.85

    matrix_output_dir: Path = Path("vm/reports")
    matrix_default_batch: int = 2

    # Domyślnie sesja użytkownika: cały matrix chodzi bez roota. `qemu:///system`
    # wymagałby praw admina do gniazda libvirtd i do /var/lib/libvirt/images,
    # a nic w tym projekcie tego nie potrzebuje.
    libvirt_uri: str = DEFAULT_LIBVIRT_URI
    image_root: Path = Field(default_factory=_default_image_root)

    capture_display_num: int = 96
    capture_screen: str = "1600x1200x24"

    tests_fast: bool = False

    def model_post_init(self, __context: object) -> None:
        if self.tests_fast:
            import os

            os.environ["SCREENWRIGHT_TESTS_FAST"] = "1"


def load_settings() -> Settings:
    return Settings()


__all__ = ["DEFAULT_LIBVIRT_URI", "Settings", "load_settings"]

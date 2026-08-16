"""Generator miniaturek (rozmiary Fedora)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal

from PIL import Image

if TYPE_CHECKING:
    from pathlib import Path

FedoraThumbnailSize = Literal["752x423", "624x351", "224x126", "112x63"]

FEDORA_THUMBNAILS: list[tuple[int, int]] = [(752, 423), (624, 351), (224, 126), (112, 63)]


def generate_thumbnails(
    source: Path, out_dir: Path, sizes: list[tuple[int, int]] = FEDORA_THUMBNAILS
) -> dict[str, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    with Image.open(source) as img:
        result: dict[str, Path] = {}
        for width, height in sizes:
            thumb = img.copy()
            thumb.thumbnail((width, height), Image.Resampling.LANCZOS)
            target = out_dir / f"{source.stem}-{width}x{height}.png"
            thumb.save(target, "PNG")
            result[f"{width}x{height}"] = target
    return result


__all__ = ["FEDORA_THUMBNAILS", "FedoraThumbnailSize", "generate_thumbnails"]

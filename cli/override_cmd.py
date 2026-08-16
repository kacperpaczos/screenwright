"""CLI subcommand: override (dawniej poc/make-override.py)."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from domains.override.catalog import (
    ElementTreeComponentFinder,
    GzipXmlCatalogLoader,
    build_override,
)
from domains.override.models import OverrideSpec
from shared.logging import log_entry

if TYPE_CHECKING:
    import argparse


def run_override(args: argparse.Namespace) -> int:
    w, h = (int(v) for v in args.source_size.split("x"))
    try:
        spec = OverrideSpec(
            component_id=args.id,
            base_url=args.base_url,
            prefix=args.prefix,
            out=Path(args.out),
            origin=args.origin,
            priority=args.priority,
            caption=args.caption,
            source_size=(w, h),
            catalog_paths=[Path(p) for p in (args.catalog or [])]
            or [Path("/usr/share/swcatalog/xml/fedora.xml.gz")],
        )
    except Exception as exc:
        log_entry(40, "cli.override.spec_invalid", error=str(exc))
        return 2
    try:
        result = build_override(
            spec, loader=GzipXmlCatalogLoader(), finder=ElementTreeComponentFinder()
        )
    except LookupError as exc:
        log_entry(40, "cli.override.not_found", error=str(exc))
        return 3
    log_entry(
        20,
        "cli.override.done",
        out=str(result.out_path),
        replaced=result.replaced_screenshots,
    )
    return 0

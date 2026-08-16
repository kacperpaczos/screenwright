"""CLI subcommand: collect (TODO §1)."""

import argparse
import json
from pathlib import Path

from domains.corpus.all import CollectRunner, CollectSpec
from shared.logging import log_entry


def _load_apps(path: Path) -> list[str]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(raw, dict) and "apps" in raw:
        items = raw["apps"]
    elif isinstance(raw, list):
        items = raw
    else:
        raise ValueError(f'apps.json must be a list or {{"apps": [...]}}, got {type(raw).__name__}')
    out: list[str] = []
    for item in items:
        if isinstance(item, str):
            out.append(item)
        elif isinstance(item, dict):
            app_id = item.get("id") or item.get("app_id")
            if app_id:
                out.append(app_id)
    return out


def run_collect(args: argparse.Namespace) -> int:
    apps_path = Path(args.apps)
    if not apps_path.exists():
        log_entry(40, "cli.collect.apps_missing", path=str(apps_path))
        return 2
    try:
        apps = _load_apps(apps_path)
    except (json.JSONDecodeError, ValueError) as exc:
        log_entry(40, "cli.collect.apps_invalid", error=str(exc))
        return 2
    if not apps:
        log_entry(40, "cli.collect.apps_empty", path=str(apps_path))
        return 2
    distros = tuple(d.strip() for d in args.distros.split(",") if d.strip())
    spec = CollectSpec.from_cli(
        apps=apps,
        distros=distros,
        output_root=Path(args.output),
        dry_run=args.dry_run,
        download_media=not args.skip_media,
    )
    runner = CollectRunner(spec)
    counts = runner.run()
    log_entry(20, "cli.collect.done", counts=counts)
    return 0

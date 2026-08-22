"""CLI subcommand: collect (TODO §1)."""

import argparse
import json
from pathlib import Path

from domains.corpus.all import CollectRunner, CollectSpec
from domains.corpus.guest import import_guest
from domains.corpus.index import IndexWriter
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
    if getattr(args, "source", "remote") == "guest":
        return _run_collect_guest(args)
    if not args.apps:
        log_entry(40, "cli.collect.apps_required", note="--source remote wymaga --apps")
        return 2
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


def _run_collect_guest(args: argparse.Namespace) -> int:
    """Import katalogów z kolektorów (`ansible/playbooks/collect.yml`) do indeksu korpusu."""
    guest_dir = Path(getattr(args, "guest_dir", "corpus/guest"))
    if not guest_dir.is_dir():
        log_entry(40, "cli.collect.guest_dir_missing", path=str(guest_dir))
        return 2
    apps: list[str] | None = None
    if args.apps:
        apps_path = Path(args.apps)
        if not apps_path.exists():
            log_entry(40, "cli.collect.apps_missing", path=str(apps_path))
            return 2
        apps = _load_apps(apps_path)
    distros = tuple(d.strip() for d in args.distros.split(",") if d.strip())
    writer = IndexWriter(Path(args.output))
    counts = import_guest(
        guest_dir,
        writer,
        distros=distros or None,
        apps=apps,
        download_media=not args.skip_media,
        max_media=getattr(args, "max_media", None),
        dry_run=args.dry_run,
    )
    log_entry(20, "cli.collect.done", source="guest", counts=counts)
    return 0

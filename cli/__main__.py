"""CLI entrypoint — `python -m cli <subcommand>`."""

from __future__ import annotations

import argparse
import sys
from typing import TYPE_CHECKING

from cli.capture_cmd import run_capture
from cli.collect_cmd import run_collect
from cli.matrix_cmd import run_matrix_execute, run_matrix_plan
from cli.override_cmd import run_override
from cli.serve_cmd import run_serve_start, run_serve_status, run_serve_stop
from cli.vm_cmd import add_vm_parser

if TYPE_CHECKING:
    from collections.abc import Sequence


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="screenwright",
        description="Headless screenshot capture, corpus, and VM matrix",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_capture = sub.add_parser("capture", help="przechwyć okno aplikacji")
    p_capture.add_argument("--cmd", required=True)
    p_capture.add_argument("--out", required=True)
    p_capture.add_argument("--timeout", type=float, default=40.0)
    p_capture.add_argument("--settle-timeout", type=float, default=20.0)
    p_capture.add_argument("--min-wait", type=float, default=0.0)
    p_capture.add_argument("--stable-frames", type=int, default=2)
    p_capture.add_argument("--require-change", action="store_true")

    p_collect = sub.add_parser("collect", help="zbierz screenshoty ze źródeł")
    p_collect.add_argument(
        "--source",
        choices=["remote", "guest"],
        default="remote",
        help="remote = publiczne endpointy per aplikacja; guest = katalogi zebrane z kolektorów (Ansible)",
    )
    p_collect.add_argument(
        "--apps", help="lista aplikacji (wymagana dla --source remote; filtr dla guest)"
    )
    p_collect.add_argument("--distros", required=True)
    p_collect.add_argument(
        "--guest-dir", default="corpus/guest", help="katalog z fetch-ami Ansible"
    )
    p_collect.add_argument(
        "--max-media",
        type=int,
        default=None,
        help="ile mediów pobrać na hoście w tym przebiegu (guest)",
    )
    p_collect.add_argument("--output", default="corpus")
    p_collect.add_argument("--dry-run", action="store_true")
    p_collect.add_argument(
        "--skip-media",
        action="store_true",
        help="pomiń pobieranie bajtów obrazów (zapisuj tylko metadane z media/unfetched.png)",
    )

    p_matrix = sub.add_parser("matrix", help="planuj lub wykonaj matrycę VM")
    p_matrix.add_argument("--spec", required=True)
    p_matrix.add_argument(
        "--execute",
        action="store_true",
        help="wykonaj zamiast planować; spec z dry_run=true i tak odmówi (blokada)",
    )
    p_matrix.add_argument(
        "--backend",
        choices=["virsh", "fake"],
        default="virsh",
        help="backend dla --execute (virsh=wymaga libvirt; fake=symulacja)",
    )
    p_matrix.add_argument("--output", default="vm/reports/matrix-report.json")
    p_matrix.add_argument(
        "--store-proxy-port",
        type=int,
        default=8900,
        help="port lokalnego snap-store-proxy (gdy DistroSpec.store_proxy == snap-store)",
    )
    p_matrix.add_argument(
        "--cli-serve-base",
        default="http://127.0.0.1:8899",
        help="URL serwera screenshotów (cli serve), na który wskazują media w snap-store-proxy",
    )
    p_matrix.add_argument(
        "--media-dir",
        default="poc/media",
        help="katalog serwowany przez `cli serve` — z niego budowane są URL-e mediów",
    )
    p_matrix.add_argument(
        "--work-root",
        default=None,
        help="katalog overlayów i zrzutów przebiegu (domyślnie <image_root>/runs; nie tmpfs)",
    )
    p_matrix.add_argument(
        "--warm-root",
        default=None,
        help="katalog szablonów warm cache (domyślnie <image_root>/warm dla --backend virsh)",
    )
    p_matrix.add_argument(
        "--no-warm-cache",
        action="store_true",
        help="zawsze zimny boot, bez save/restore",
    )
    p_matrix.add_argument(
        "--rebuild-warm-cache",
        action="store_true",
        help="skasuj szablony warm dystrybucji ze specu przed przebiegiem",
    )

    p_override = sub.add_parser("override", help="zbuduj override katalogu AppStream")
    p_override.add_argument("--id", required=True)
    p_override.add_argument("--base-url", required=True)
    p_override.add_argument("--prefix", required=True)
    p_override.add_argument("--out", required=True)
    p_override.add_argument("--origin", default="screenwright")
    p_override.add_argument("--priority", type=int, default=1)
    p_override.add_argument(
        "--caption", default="screenwright - generated automatically under Xvfb"
    )
    p_override.add_argument("--source-size", default="640x480")
    p_override.add_argument("--catalog", action="append", default=None)

    p_serve = sub.add_parser("serve", help="lokalny serwer obrazów")
    serve_sub = p_serve.add_subparsers(dest="serve_action", required=True)
    p_serve_start = serve_sub.add_parser("start")
    p_serve_start.add_argument("--port", type=int, default=8899)
    p_serve_start.add_argument("--host", default="127.0.0.1")
    p_serve_start.add_argument("--directory", default="poc/media")
    serve_sub.add_parser("stop")
    p_serve_status = serve_sub.add_parser("status")
    p_serve_status.add_argument("--port", type=int, default=8899)
    p_serve_status.add_argument("--host", default="127.0.0.1")

    add_vm_parser(sub)

    return parser


def dispatch(args: argparse.Namespace) -> int:
    if args.command == "capture":
        return run_capture(args)
    if args.command == "collect":
        return run_collect(args)
    if args.command == "matrix":
        if args.execute:
            return run_matrix_execute(args)
        return run_matrix_plan(args)
    if args.command == "override":
        return run_override(args)
    if args.command == "serve":
        if args.serve_action == "start":
            return run_serve_start(args)
        if args.serve_action == "stop":
            return run_serve_stop()
        return run_serve_status(args)
    if args.command == "vm":
        return args.func(args)
    return 2


def main(argv: Sequence[str] | None = None) -> int:
    if argv is None:
        argv = sys.argv[1:]
    parser = build_parser()
    args = parser.parse_args(list(argv))
    return dispatch(args)


if __name__ == "__main__":
    sys.exit(main())

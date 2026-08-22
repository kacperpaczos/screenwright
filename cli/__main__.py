"""CLI entrypoint — `python -m cli <subcommand>`."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import TYPE_CHECKING

from cli.capture_cmd import run_capture
from cli.collect_cmd import run_collect
from cli.override_cmd import run_override
from cli.serve_cmd import run_serve_start, run_serve_status, run_serve_stop
from cli.vm_cmd import add_vm_parser

if TYPE_CHECKING:
    from collections.abc import Sequence


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="screenwright",
        description="Headless screenshot capture and corpus",
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
    p_collect.add_argument(
        "--hydrate-media",
        type=int,
        default=None,
        metavar="N",
        help="pobierz bajty dla N wpisów już w indeksie (guest) — same URL-e stają się plikami",
    )
    p_collect.add_argument(
        "--hydrate-per-app",
        type=int,
        default=None,
        help="limit zdjęć na aplikację przy --hydrate-media",
    )
    p_collect.add_argument("--output", default="corpus")
    p_collect.add_argument("--dry-run", action="store_true")
    p_collect.add_argument(
        "--skip-media",
        action="store_true",
        help="pomiń pobieranie bajtów obrazów (zapisuj tylko metadane z media/unfetched.png)",
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
    p_override.add_argument(
        "--patch",
        action="store_true",
        help=(
            "podmień <screenshots> komponentu w SAMYM katalogu bazowym (--out może być "
            "tym samym plikiem co --catalog). Metoda, którą sklep faktycznie renderuje — "
            "osobny plik override libappstream tylko UNIONuje ze zrzutami bazy."
        ),
    )

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

    p_vc = sub.add_parser(
        "visualcheck", help="dowód wizualny cel 2: boot → override → zrzut → match markera"
    )
    p_vc.add_argument("--golden", required=True, help="ścieżka do golden qcow2")
    p_vc.add_argument("--component-id", required=True, help="np. GameConqueror.desktop")
    p_vc.add_argument("--prefix", required=True, help="prefiks plików mediów (np. gimp)")
    p_vc.add_argument("--media-dir", required=True, help="katalog z <prefix>-*.png (+ marker)")
    p_vc.add_argument(
        "--catalog",
        default="/usr/share/swcatalog/xml/fedora.xml.gz",
        help="katalog w gościu do podmiany (XML rpm lub DEP-11 YAML)",
    )
    p_vc.add_argument(
        "--store-cmd",
        default="gnome-software --details={id}",
        help="szablon otwarcia sklepu; {id} → component-id (np. "
        "'plasma-discover --application appstream:{id}')",
    )
    p_vc.add_argument(
        "--marker", default=None, help="obraz markera (domyślnie <prefix>-source.png)"
    )
    p_vc.add_argument("--out", default="visualcheck.png", help="gdzie zapisać zrzut")
    p_vc.add_argument("--name", default="sw-visualcheck")
    p_vc.add_argument("--ssh-port", type=int, default=2222)
    p_vc.add_argument("--user", default="test")
    p_vc.add_argument("--key", default=str(Path.home() / ".ssh/screenwright_ubuntu"))
    p_vc.add_argument("--osinfo", default="fedora40")
    p_vc.add_argument("--memory", type=int, default=4096)
    p_vc.add_argument("--media-port", type=int, default=8080)
    p_vc.add_argument("--threshold", type=float, default=0.03)
    p_vc.add_argument("--libvirt-uri", default="qemu:///session")
    p_vc.add_argument(
        "--work-dir", default=str(Path.home() / ".local/share/screenwright/images/vc")
    )

    return parser


def dispatch(args: argparse.Namespace) -> int:
    if args.command == "capture":
        return run_capture(args)
    if args.command == "collect":
        return run_collect(args)
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
    if args.command == "visualcheck":
        from cli.visualcheck_cmd import run_visualcheck

        return run_visualcheck(args)
    return 2


def main(argv: Sequence[str] | None = None) -> int:
    if argv is None:
        argv = sys.argv[1:]
    parser = build_parser()
    args = parser.parse_args(list(argv))
    return dispatch(args)


if __name__ == "__main__":
    sys.exit(main())
